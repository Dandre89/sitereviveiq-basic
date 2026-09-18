"""
Basic -> Pro account upgrade. One-way only: a Basic customer can move to
Pro (carrying their whole account with them), there is no self-serve
path back the other way.

Why this can live entirely inside the Basic codebase: Basic and Pro are
separate Django projects with separate GitHub repos and separate Render
services, but they share ONE physical Postgres instance, isolated from
each other only by schema ("basic" vs "pro" — see config.settings'
POSTGRES_SCHEMA docstring). Every table Basic has is either identical in
shape to Pro's version or a strict subset (Pro just carries a few extra
nullable columns for features Basic doesn't have, e.g.
reports_report.roadmap_id) — confirmed directly against live
`information_schema.columns` output for every table involved, the same
"trust the live DB, not a source snapshot" discipline used when building
the internal admin console. That means migrating a workspace is a
straight cross-schema row copy: fully-qualified `INSERT INTO
pro.<table> SELECT ... FROM basic.<table>` statements run through this
app's own database connection, in dependency order. No second DATABASES
alias, no mirrored model classes, no HTTP call to the Pro service at
all.

Flow, end to end:
1. An owner clicks "Upgrade to Pro" in Settings (see apps.billing.views
   .upgrade_to_pro) -> check_upgrade_eligibility() runs first so we never
   charge someone we then can't migrate.
2. create_upgrade_checkout_session() sends them through a REAL Stripe
   Checkout Session for a Pro price (same Product/Prices already created
   for the standalone Pro app) — metadata carries upgrade_to_pro=true and
   the Basic workspace id.
3. On success, complete_upgrade_from_checkout_session() runs — from
   BOTH the synchronous checkout_success view and the
   checkout.session.completed webhook, same dual-path pattern as
   services.link_subscription_from_checkout_session, and safe to run
   from both: idempotent via Subscription.migrated_to_pro_at (the
   permanent guard) plus `ON CONFLICT (id) DO NOTHING` on every insert
   (a second layer, in case this ever runs twice before the guard is
   saved).
4. The Basic subscription is stamped migrated_to_pro_at (permanent
   record) and its real Stripe subscription is canceled — SO the
   customer stops being billed on Basic. SubscriptionEnforcementMiddleware
   checks migrated_to_pro_at first and shows a "you're on Pro now" page
   with a link to Pro's login, instead of the generic locked page.
5. Their password hash is copied byte-for-byte, so the same email +
   password that logged into Basic logs into Pro immediately — no reset
   needed, even though these are two completely separate login systems.

Known gap, worth flagging rather than silently handling: if the
migration itself fails partway (e.g. a genuine email/slug collision with
an existing, unrelated Pro account — checked for up front, but a race is
theoretically possible), the customer has already paid Stripe for a Pro
subscription that doesn't have data behind it yet. That's caught and
logged loudly (see complete_upgrade_from_checkout_session) rather than
silently swallowed, but resolving it today means a manual look via the
admin console or Render logs — there's no automatic refund/retry loop.
"""
import logging

import stripe
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.workspaces.models import Workspace

from .models import Subscription
from .services import _apply_stripe_subscription, build_client, StripeNotConfiguredError

logger = logging.getLogger(__name__)


class UpgradeError(Exception):
    """Raised for anything that should stop an upgrade before it charges the customer."""


class UnknownProPriceError(Exception):
    pass


def get_pro_price_id(interval: str) -> str:
    price_id = settings.STRIPE_PRICE_IDS_PRO.get(interval, "")
    if not price_id:
        raise UnknownProPriceError(
            f"No Pro Stripe price configured for interval={interval!r}. "
            "Check the STRIPE_PRICE_PRO_* environment variables."
        )
    return price_id


def check_upgrade_eligibility(workspace: Workspace) -> None:
    """
    Run before creating any Stripe Checkout Session — we never want to
    charge someone for an upgrade we already know we can't complete.
    Re-checked defensively inside the migration transaction too (the DB's
    own unique constraints are the final word), but failing fast here
    means the common case never gets anywhere near Stripe.
    """
    subscription = getattr(workspace, "subscription", None)
    if subscription is not None and subscription.is_migrated_to_pro:
        raise UpgradeError("This workspace has already been upgraded to Pro.")

    owner_membership = workspace.memberships.select_related("user").filter(
        role="owner"
    ).first()
    if owner_membership is None:
        raise UpgradeError("This workspace has no owner to migrate.")
    email = owner_membership.user.email

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pro.accounts_user WHERE email = %s", [email])
        if cursor.fetchone() is not None:
            raise UpgradeError(
                f"{email} already has an account on Pro — this looks like it needs a "
                "manual check rather than an automatic upgrade."
            )
        cursor.execute("SELECT 1 FROM pro.workspaces_workspace WHERE slug = %s", [workspace.slug])
        if cursor.fetchone() is not None:
            raise UpgradeError(
                f"A Pro workspace already uses the slug '{workspace.slug}' — this looks like "
                "it needs a manual check rather than an automatic upgrade."
            )


def create_upgrade_checkout_session(
    *, workspace: Workspace, user, interval: str, success_url: str, cancel_url: str
) -> str:
    """
    Real Stripe Checkout for a Pro subscription — not a token gesture.
    client_reference_id + metadata both carry the Basic workspace id (two
    different Stripe fields with the same value) so either the
    synchronous success view or the webhook can find their way back to
    this workspace regardless of which one Stripe delivers first.
    """
    price_id = get_pro_price_id(interval)
    client = build_client()

    session = client.v1.checkout.sessions.create({
        "mode": "subscription",
        "customer_email": user.email,
        "client_reference_id": str(workspace.id),
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "managed_payments": {"enabled": False},
        "metadata": {
            "upgrade_to_pro": "true",
            "basic_workspace_id": str(workspace.id),
            "interval": interval,
        },
    })
    return session.url


def _session_metadata(session) -> dict:
    """
    session.metadata arrives as a Stripe SDK object (StripeObject), not a
    plain dict — as of the stripe-python version pinned here, StripeObject
    no longer supports dict methods like .get() directly (calling one
    raises AttributeError via its __getattr__, since it looks for an
    attribute named "get" rather than a key). .to_dict() is the
    SDK-documented way to get a real dict back out. Every metadata read
    in this module goes through this helper so there's exactly one place
    that knows about that quirk.
    """
    metadata = getattr(session, "metadata", None)
    if metadata is None:
        return {}
    if hasattr(metadata, "to_dict"):
        return metadata.to_dict()
    return dict(metadata)


def is_upgrade_session(session) -> bool:
    return _session_metadata(session).get("upgrade_to_pro") == "true"


def complete_upgrade_from_checkout_session(session) -> Subscription | None:
    """
    Idempotent entry point, safe to call from both the synchronous
    checkout_success view and the checkout.session.completed webhook —
    whichever runs first does the work; the other sees
    migrated_to_pro_at already set and returns immediately. Returns the
    (now-migrated) Basic Subscription row, or None if this wasn't
    actually an upgrade session.
    """
    if not is_upgrade_session(session):
        return None

    workspace_id = getattr(session, "client_reference_id", None) or _session_metadata(session).get(
        "basic_workspace_id"
    )
    if not workspace_id:
        logger.error("Upgrade checkout session %s has no workspace id.", getattr(session, "id", "?"))
        return None

    subscription = Subscription.objects.select_related("workspace").filter(
        workspace_id=workspace_id
    ).first()
    if subscription is None:
        logger.error("Upgrade checkout session %s references unknown workspace %s.", session.id, workspace_id)
        return None

    if subscription.is_migrated_to_pro:
        # Already done — the other path (webhook or success view) got here first.
        return subscription

    stripe_subscription_id = getattr(session, "subscription", None)
    if not stripe_subscription_id:
        logger.error("Upgrade checkout session %s has no Stripe subscription attached.", session.id)
        return None
    if not isinstance(stripe_subscription_id, str):
        stripe_subscription_id = stripe_subscription_id.id

    client = build_client()
    stripe_sub = client.v1.subscriptions.retrieve(stripe_subscription_id)
    interval = _session_metadata(session).get("interval") or subscription.intended_interval or "monthly"

    try:
        with transaction.atomic():
            _migrate_workspace_data(str(workspace_id))
            _create_pro_subscription(
                workspace_id=str(workspace_id),
                stripe_sub=stripe_sub,
                interval=interval,
            )
            subscription.migrated_to_pro_at = timezone.now()
            subscription.migrated_to_pro_workspace_id = workspace_id
            subscription.save(update_fields=["migrated_to_pro_at", "migrated_to_pro_workspace_id"])
    except Exception:
        logger.exception(
            "Upgrade migration FAILED for workspace %s after successful Stripe payment "
            "(Stripe subscription %s) — customer has been charged but data was not migrated. "
            "Needs a manual look.",
            workspace_id,
            stripe_subscription_id,
        )
        raise

    _cancel_old_basic_subscription(subscription)
    return subscription


def _migrate_workspace_data(workspace_id: str) -> None:
    """
    The actual cross-schema copy, in dependency order (parents before
    children). websites_website.last_scan_id is a forward reference to a
    scan that doesn't exist yet at the time the website row is copied —
    inserted as NULL and fixed up in a second pass once scans_scan has
    been copied. `ON CONFLICT (id) DO NOTHING` on every insert makes each
    statement safe to re-run.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO pro.accounts_user
                (id, password, last_login, is_superuser, first_name, last_name,
                 is_staff, is_active, date_joined, email, created_at, updated_at)
            SELECT
                u.id, u.password, u.last_login, u.is_superuser, u.first_name, u.last_name,
                u.is_staff, u.is_active, u.date_joined, u.email, u.created_at, u.updated_at
            FROM basic.accounts_user u
            JOIN basic.workspaces_workspacemembership m ON m.user_id = u.id
            WHERE m.workspace_id = %(wid)s
            ON CONFLICT (id) DO NOTHING
            """,
            {"wid": workspace_id},
        )

        cursor.execute(
            """
            INSERT INTO pro.workspaces_workspace
                (id, name, slug, is_active, notify_critical_findings, notify_score_drops,
                 notify_scan_completed, notify_new_opportunities, notify_returning_issues,
                 score_drop_threshold, logo, show_powered_by, lifecycle_status,
                 created_at, updated_at)
            SELECT
                id, name, slug, is_active, notify_critical_findings, notify_score_drops,
                notify_scan_completed, notify_new_opportunities, notify_returning_issues,
                score_drop_threshold, logo, show_powered_by, lifecycle_status,
                created_at, updated_at
            FROM basic.workspaces_workspace
            WHERE id = %(wid)s
            ON CONFLICT (id) DO NOTHING
            """,
            {"wid": workspace_id},
        )

        cursor.execute(
            """
            INSERT INTO pro.workspaces_workspacemembership
                (id, role, created_at, user_id, workspace_id)
            SELECT id, role, created_at, user_id, workspace_id
            FROM basic.workspaces_workspacemembership
            WHERE workspace_id = %(wid)s
            ON CONFLICT (id) DO NOTHING
            """,
            {"wid": workspace_id},
        )

        cursor.execute(
            """
            INSERT INTO pro.websites_website
                (id, name, submitted_url, canonical_url, normalized_host, website_type, status,
                 monitoring_frequency, max_pages, max_depth, created_at, updated_at,
                 created_by_id, last_scan_id, tracks_competitor_for_id, workspace_id)
            SELECT
                id, name, submitted_url, canonical_url, normalized_host, website_type, status,
                monitoring_frequency, max_pages, max_depth, created_at, updated_at,
                created_by_id, NULL, tracks_competitor_for_id, workspace_id
            FROM basic.websites_website
            WHERE workspace_id = %(wid)s
            ON CONFLICT (id) DO NOTHING
            """,
            {"wid": workspace_id},
        )

        cursor.execute(
            """
            INSERT INTO pro.scans_scan
                (id, status, trigger, root_url, max_pages, max_depth, pages_discovered,
                 pages_attempted, pages_completed, pages_failed, started_at, completed_at,
                 celery_task_id, crawler_version, analyzer_version, failure_code,
                 failure_message, summary_data, overall_score, category_scores, created_at,
                 requested_by_id, website_id, workspace_id)
            SELECT
                id, status, trigger, root_url, max_pages, max_depth, pages_discovered,
                pages_attempted, pages_completed, pages_failed, started_at, completed_at,
                celery_task_id, crawler_version, analyzer_version, failure_code,
                failure_message, summary_data, overall_score, category_scores, created_at,
                requested_by_id, website_id, workspace_id
            FROM basic.scans_scan
            WHERE workspace_id = %(wid)s
            ON CONFLICT (id) DO NOTHING
            """,
            {"wid": workspace_id},
        )

        # Fix-up pass: now that scans exist on the Pro side, backfill the
        # website's last_scan_id from Basic's own value.
        cursor.execute(
            """
            UPDATE pro.websites_website AS pw
            SET last_scan_id = bw.last_scan_id
            FROM basic.websites_website AS bw
            WHERE pw.id = bw.id AND bw.workspace_id = %(wid)s AND bw.last_scan_id IS NOT NULL
            """,
            {"wid": workspace_id},
        )

        cursor.execute(
            """
            INSERT INTO pro.scans_scanpage
                (id, requested_url, normalized_url, final_url, parent_url, crawl_depth,
                 fetch_status, http_status_code, content_type, response_time_ms,
                 response_size_bytes, redirect_count, redirect_chain, page_title,
                 meta_description, canonical_url, robots_directives, h1_count, h2_count,
                 word_count, internal_link_count, external_link_count, image_count,
                 images_without_alt_count, has_viewport, has_mixed_content, is_indexable,
                 has_phone_link, has_contact_form, has_cta_link, html_hash, text_hash,
                 extracted_data, error_code, error_message, fetched_at, scan_id, website_id,
                 workspace_id)
            SELECT
                id, requested_url, normalized_url, final_url, parent_url, crawl_depth,
                fetch_status, http_status_code, content_type, response_time_ms,
                response_size_bytes, redirect_count, redirect_chain, page_title,
                meta_description, canonical_url, robots_directives, h1_count, h2_count,
                word_count, internal_link_count, external_link_count, image_count,
                images_without_alt_count, has_viewport, has_mixed_content, is_indexable,
                has_phone_link, has_contact_form, has_cta_link, html_hash, text_hash,
                extracted_data, error_code, error_message, fetched_at, scan_id, website_id,
                workspace_id
            FROM basic.scans_scanpage
            WHERE workspace_id = %(wid)s
            ON CONFLICT (id) DO NOTHING
            """,
            {"wid": workspace_id},
        )

        cursor.execute(
            """
            INSERT INTO pro.scans_scanevent (id, level, event_type, message, event_data, created_at, scan_id)
            SELECT e.id, e.level, e.event_type, e.message, e.event_data, e.created_at, e.scan_id
            FROM basic.scans_scanevent e
            JOIN basic.scans_scan s ON s.id = e.scan_id
            WHERE s.workspace_id = %(wid)s
            ON CONFLICT (id) DO NOTHING
            """,
            {"wid": workspace_id},
        )

        cursor.execute(
            """
            INSERT INTO pro.scans_pagelink
                (id, destination_url, normalized_destination_url, link_type, anchor_text,
                 rel_value, is_nofollow, scan_id, destination_page_id, source_page_id)
            SELECT
                l.id, l.destination_url, l.normalized_destination_url, l.link_type, l.anchor_text,
                l.rel_value, l.is_nofollow, l.scan_id, l.destination_page_id, l.source_page_id
            FROM basic.scans_pagelink l
            JOIN basic.scans_scan s ON s.id = l.scan_id
            WHERE s.workspace_id = %(wid)s
            ON CONFLICT (id) DO NOTHING
            """,
            {"wid": workspace_id},
        )

        cursor.execute(
            """
            INSERT INTO pro.findings_issue
                (id, rule_key, fingerprint, title, category, current_severity, business_impact,
                 affected_scope, recommendation, estimated_effort, priority_class, status,
                 ignored_reason, first_seen_at, last_seen_at, resolved_at, first_seen_scan_id,
                 last_seen_scan_id, website_id, workspace_id)
            SELECT
                id, rule_key, fingerprint, title, category, current_severity, business_impact,
                affected_scope, recommendation, estimated_effort, priority_class, status,
                ignored_reason, first_seen_at, last_seen_at, resolved_at, first_seen_scan_id,
                last_seen_scan_id, website_id, workspace_id
            FROM basic.findings_issue
            WHERE workspace_id = %(wid)s
            ON CONFLICT (id) DO NOTHING
            """,
            {"wid": workspace_id},
        )

        cursor.execute(
            """
            INSERT INTO pro.findings_findingoccurrence (id, severity, evidence, created_at, page_id, scan_id, issue_id)
            SELECT o.id, o.severity, o.evidence, o.created_at, o.page_id, o.scan_id, o.issue_id
            FROM basic.findings_findingoccurrence o
            JOIN basic.findings_issue i ON i.id = o.issue_id
            WHERE i.workspace_id = %(wid)s
            ON CONFLICT (id) DO NOTHING
            """,
            {"wid": workspace_id},
        )

        cursor.execute(
            """
            INSERT INTO pro.reports_report
                (id, report_type, title, content, generated_at, comparison_id, generated_by_id,
                 roadmap_id, scan_id, website_id, workspace_id)
            SELECT
                id, report_type, title, content, generated_at, NULL, generated_by_id,
                NULL, scan_id, website_id, workspace_id
            FROM basic.reports_report
            WHERE workspace_id = %(wid)s
            ON CONFLICT (id) DO NOTHING
            """,
            {"wid": workspace_id},
        )

        cursor.execute(
            """
            INSERT INTO pro.reports_reportsharelink
                (id, token, created_at, expires_at, view_count, last_viewed_at, revoked,
                 created_by_id, report_id)
            SELECT s.id, s.token, s.created_at, s.expires_at, s.view_count, s.last_viewed_at,
                   s.revoked, s.created_by_id, s.report_id
            FROM basic.reports_reportsharelink s
            JOIN basic.reports_report r ON r.id = s.report_id
            WHERE r.workspace_id = %(wid)s
            ON CONFLICT (id) DO NOTHING
            """,
            {"wid": workspace_id},
        )

        cursor.execute(
            """
            INSERT INTO pro.monitoring_notification
                (id, notification_type, title, message, is_read, email_sent, created_at,
                 comparison_id, recipient_id, scan_id, website_id, workspace_id)
            SELECT
                id, notification_type, title, message, is_read, email_sent, created_at,
                NULL, recipient_id, scan_id, website_id, workspace_id
            FROM basic.monitoring_notification
            WHERE workspace_id = %(wid)s
            ON CONFLICT (id) DO NOTHING
            """,
            {"wid": workspace_id},
        )


def _create_pro_subscription(*, workspace_id: str, stripe_sub, interval: str) -> None:
    """
    Unlike every table above, this is a fresh row with real values from
    the NEW Stripe subscription — not a copy of Basic's old one. Pro's
    billing_subscription has one extra column Basic's doesn't
    (intended_plan), set to 'pro' here since that's the whole point.
    """
    price_id = ""
    items = getattr(getattr(stripe_sub, "items", None), "data", None) or []
    if items:
        price_id = items[0].price.id

    period_end = None
    raw_period_end = (
        getattr(items[0], "current_period_end", None) if items else None
    ) or getattr(stripe_sub, "current_period_end", None)
    if raw_period_end:
        import datetime as dt
        period_end = dt.datetime.fromtimestamp(raw_period_end, tz=dt.timezone.utc)

    customer = getattr(stripe_sub, "customer", None)
    customer_id = customer if isinstance(customer, str) else getattr(customer, "id", "")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO pro.billing_subscription
                (id, workspace_id, stripe_customer_id, stripe_subscription_id, stripe_price_id,
                 intended_plan, intended_interval, status, current_period_end,
                 cancel_at_period_end, created_at, updated_at)
            VALUES
                (gen_random_uuid(), %(wid)s, %(customer_id)s, %(sub_id)s, %(price_id)s,
                 'pro', %(interval)s, %(status)s, %(period_end)s, %(cancel_at_period_end)s,
                 now(), now())
            ON CONFLICT (workspace_id) DO NOTHING
            """,
            {
                "wid": workspace_id,
                "customer_id": customer_id,
                "sub_id": stripe_sub.id,
                "price_id": price_id,
                "interval": interval,
                "status": stripe_sub.status,
                "period_end": period_end,
                "cancel_at_period_end": bool(getattr(stripe_sub, "cancel_at_period_end", False)),
            },
        )


def _cancel_old_basic_subscription(subscription: Subscription) -> None:
    """
    Best-effort: runs after the migration transaction has already
    committed, so a failure here never rolls back a successful
    migration — it just means Darren cancels the old Basic subscription
    by hand later (it'll show up as a discrepancy in the admin console's
    billing linkage screen). Logged loudly either way.
    """
    if not subscription.stripe_subscription_id:
        return
    try:
        client = build_client()
        stripe_sub = client.v1.subscriptions.cancel(subscription.stripe_subscription_id)
        _apply_stripe_subscription(subscription, stripe_sub)
        subscription.save()
    except StripeNotConfiguredError:
        logger.warning("Couldn't cancel old Basic subscription for workspace %s — Stripe not configured.", subscription.workspace_id)
    except stripe.StripeError:
        logger.exception(
            "Couldn't cancel old Basic subscription %s for workspace %s after a successful "
            "upgrade — needs a manual cancel in Stripe.",
            subscription.stripe_subscription_id,
            subscription.workspace_id,
        )
