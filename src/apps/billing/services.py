"""
Thin wrapper around the Stripe API, covering two account-creation paths
that both land on the same Subscription row:

1. Sales-assisted (any manually-arranged deal): an operator creates the
   customer + subscription directly in the Stripe Dashboard, pastes the
   two IDs into this workspace's Subscription row (Django admin), and
   the "Sync from Stripe" admin action or the webhook below keeps
   status/current_period_end current from there on.
2. Self-serve (this build's normal path, added Sept 2026): a new signup
   picks a billing interval, create_signup_checkout_session sends them
   to a real Stripe Checkout Session (charged immediately — this build
   has no trial), and link_subscription_from_checkout_session (called
   from both the synchronous success view and the
   checkout.session.completed webhook) stamps the resulting
   customer/subscription onto that same Subscription row. This build
   only ever sells Basic — there's no plan parameter, unlike the Pro
   codebase's version of this file. See apps.accounts.views.signup for
   where the flow starts.

Uses the stripe-python v15 client-based calling convention
(stripe.StripeClient(...).v1.<resource>.<method>(...)) rather than the
older global stripe.api_key = ... + stripe.<Resource>.<method>(...)
style — the client style is what Stripe's own current docs lead with.

Every public function here goes through build_client(), which raises
StripeNotConfiguredError if settings.STRIPE_SECRET_KEY is blank, rather
than letting a bare API call fail with a confusing auth error — this
mirrors the EMAIL_HOST dev/prod split in config.settings.base, and is
what lets SubscriptionEnforcementMiddleware treat "Stripe not
configured" as "this environment doesn't enforce billing" instead of a
hard failure.
"""
import datetime as dt

import stripe
from django.conf import settings

from .models import Subscription


class StripeNotConfiguredError(Exception):
    pass


def build_client() -> "stripe.StripeClient":
    if not settings.STRIPE_SECRET_KEY:
        raise StripeNotConfiguredError(
            "STRIPE_SECRET_KEY isn't set in this environment — billing calls are disabled."
        )
    return stripe.StripeClient(settings.STRIPE_SECRET_KEY)


class UnknownPriceError(Exception):
    pass


def get_price_id(interval: str) -> str:
    """
    interval is "monthly" or "annual". This build only sells Basic, so
    there's no plan parameter (contrast with the Pro codebase's version
    of this function). Raises UnknownPriceError rather than returning a
    blank string so a checkout session never silently gets created with
    an empty price — see settings.STRIPE_PRICE_IDS for where these
    actually come from.
    """
    price_id = settings.STRIPE_PRICE_IDS.get(interval, "")
    if not price_id:
        raise UnknownPriceError(
            f"No Stripe price configured for interval={interval!r}. "
            "Check the STRIPE_PRICE_* environment variables."
        )
    return price_id


def create_signup_checkout_session(
    *, subscription: Subscription, user, interval: str, success_url: str, cancel_url: str
) -> str:
    """
    Creates a Stripe Checkout Session for a brand-new (or still-unlinked)
    workspace's first subscription. Self-serve counterpart to the
    sales-assisted "operator pastes IDs into admin" flow above — this is
    the only place in the app that creates a Checkout Session. No trial:
    this build charges immediately on signup (contrast with the Pro
    codebase, which gives a 14-day trial) — Basic's product role is the
    cheap, no-fuss plan, not a trial entry point.

    client_reference_id carries the workspace id — that's what the
    synchronous success-page lookup and the checkout.session.completed
    webhook use (see link_subscription_from_checkout_session) to find
    which workspace this session belongs to.
    """
    price_id = get_price_id(interval)
    client = build_client()

    session = client.v1.checkout.sessions.create({
        "mode": "subscription",
        "customer_email": user.email,
        "client_reference_id": str(subscription.workspace_id),
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        # This Stripe test account has "Managed Payments" on by default,
        # which requires every line-item Product to carry a tax_code —
        # not something we've set up, and not relevant to a test-mode
        # self-serve flow. Disabling it per-session (Stripe's own
        # suggested fix) avoids depending on Product-level tax config
        # that isn't part of anything decided in the pricing docs.
        "managed_payments": {"enabled": False},
    })
    return session.url


def link_subscription_from_checkout_session(session) -> Subscription | None:
    """
    Idempotent: pulls the workspace id off a completed Checkout Session,
    retrieves the real Stripe subscription it produced, and stamps that
    onto the matching (still-unlinked) Subscription row. Called from
    both the synchronous checkout-success view (so a customer isn't
    stuck waiting on webhook delivery, especially in local dev where a
    webhook forwarder might not be running) and the checkout.session.completed
    webhook handler below (as the durable, guaranteed-eventually-correct
    path). Safe to run twice for the same session — it just re-syncs the
    same data.
    """
    workspace_id = getattr(session, "client_reference_id", None)
    if not workspace_id:
        return None

    subscription = Subscription.objects.filter(workspace_id=workspace_id).first()
    if subscription is None:
        return None

    stripe_subscription_id = getattr(session, "subscription", None)
    if not stripe_subscription_id:
        return None
    if not isinstance(stripe_subscription_id, str):
        stripe_subscription_id = stripe_subscription_id.id

    client = build_client()
    stripe_sub = client.v1.subscriptions.retrieve(stripe_subscription_id)
    subscription.stripe_subscription_id = stripe_sub.id
    _apply_stripe_subscription(subscription, stripe_sub)
    subscription.save()
    return subscription


def create_billing_portal_session(subscription: Subscription, return_url: str) -> str:
    """
    Returns a one-time URL to Stripe's hosted Billing Portal, where the
    workspace owner can update their card, view past invoices, or cancel.
    Requires the workspace to already be linked to a Stripe customer —
    see Subscription.is_linked; callers should check that first and show
    a "not set up yet" state instead of calling this.
    """
    client = build_client()
    session = client.v1.billing_portal.sessions.create({
        "customer": subscription.stripe_customer_id,
        "return_url": return_url,
    })
    return session.url


def sync_subscription_from_stripe(subscription: Subscription) -> Subscription:
    """
    Pulls current status/period-end/price straight from the Stripe API
    for a subscription that's already linked (has stripe_subscription_id
    set) — used by the admin "Sync from Stripe" action right after an
    operator links a workspace, and as a manual fallback if a webhook
    delivery is ever missed.
    """
    if not subscription.stripe_subscription_id:
        raise ValueError("This workspace isn't linked to a Stripe subscription yet.")

    client = build_client()
    stripe_sub = client.v1.subscriptions.retrieve(subscription.stripe_subscription_id)
    _apply_stripe_subscription(subscription, stripe_sub)
    subscription.save()
    return subscription


def _apply_stripe_subscription(subscription: Subscription, stripe_sub) -> None:
    # stripe-python v15's client-based API returns typed resource objects,
    # not the old dict-subclassed StripeObject — .get()/dict-style access
    # raises a "not a dict, use .to_dict()" error, so everything here goes
    # through attribute access (getattr with a default for optional fields).
    subscription.status = stripe_sub.status
    subscription.cancel_at_period_end = bool(getattr(stripe_sub, "cancel_at_period_end", False))

    period_end = getattr(stripe_sub, "current_period_end", None)
    subscription.current_period_end = (
        dt.datetime.fromtimestamp(period_end, tz=dt.timezone.utc) if period_end else None
    )

    items = getattr(stripe_sub, "items", None)
    items_data = getattr(items, "data", None) or []
    if items_data:
        subscription.stripe_price_id = items_data[0].price.id

    customer = getattr(stripe_sub, "customer", None)
    if customer:
        # customer is a plain string ID unless the caller expanded it.
        subscription.stripe_customer_id = customer if isinstance(customer, str) else customer.id


def handle_webhook_event(event) -> None:
    """
    Dispatches a verified Stripe webhook event. Only subscription and
    invoice events touch a Subscription row — everything else is
    ignored (return silently, not an error) since a Stripe endpoint
    commonly receives a broader event stream than any one handler cares
    about; deciding which events actually get sent is a Dashboard-side
    concern, not this function's job.
    """
    event_type = event.type
    data_object = event.data.object

    if event_type == "checkout.session.completed":
        link_subscription_from_checkout_session(data_object)
    elif event_type.startswith("customer.subscription."):
        _sync_from_subscription_object(data_object)
    elif event_type in ("invoice.paid", "invoice.payment_failed"):
        subscription_id = getattr(data_object, "subscription", None)
        if subscription_id:
            _resync_subscription_id(subscription_id)


def _sync_from_subscription_object(stripe_sub) -> None:
    subscription = Subscription.objects.filter(stripe_subscription_id=stripe_sub.id).first()
    if subscription is None:
        # Not a subscription we know about yet (e.g. created directly in
        # the Dashboard but not linked to a workspace) — nothing to update.
        return
    _apply_stripe_subscription(subscription, stripe_sub)
    subscription.save()


def _resync_subscription_id(stripe_subscription_id: str) -> None:
    subscription = Subscription.objects.filter(stripe_subscription_id=stripe_subscription_id).first()
    if subscription is None:
        return
    sync_subscription_from_stripe(subscription)
