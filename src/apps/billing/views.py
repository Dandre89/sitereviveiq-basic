import logging

import stripe
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from django.conf import settings

from apps.workspaces.models import WorkspaceMembership

from . import services, upgrade

logger = logging.getLogger(__name__)


def _is_workspace_owner(request) -> bool:
    if request.workspace is None:
        return False
    return WorkspaceMembership.objects.filter(
        workspace=request.workspace, user=request.user, role=WorkspaceMembership.Role.OWNER
    ).exists()


def pricing(request):
    """
    Public plan page for this build — Basic only (no Pro/Enterprise
    cards here; contrast with the Pro codebase's version of this view),
    with a Monthly/Annual toggle (plain ?interval= link, no JS
    required). The button goes to accounts:signup with ?interval=.
    Figures match SiteReviveIQ_Pricing_Strategy.md exactly.
    """
    interval = request.GET.get("interval", "monthly")
    if interval not in ("monthly", "annual"):
        interval = "monthly"

    if interval == "annual":
        price, note = "23.20", "billed $278.40/yr"
    else:
        price, note = "29", None

    return render(request, "billing/pricing.html", {"interval": interval, "price": price, "note": note})


def checkout_success(request):
    """
    Stripe redirects here after a successful Checkout (success_url
    includes ?session_id={CHECKOUT_SESSION_ID}). Does the linking
    synchronously so the new customer isn't stuck waiting on webhook
    delivery — see services.link_subscription_from_checkout_session,
    which is written to be safe to also run again from the
    checkout.session.completed webhook.
    """
    session_id = request.GET.get("session_id")
    if not session_id:
        messages.error(request, "Missing checkout session — if you completed payment, log in and check Settings.")
        return redirect("core:dashboard" if request.user.is_authenticated else "accounts:login")

    try:
        client = services.build_client()
    except services.StripeNotConfiguredError:
        messages.error(request, "Billing isn't configured in this environment yet.")
        return redirect("core:dashboard" if request.user.is_authenticated else "accounts:login")

    try:
        session = client.v1.checkout.sessions.retrieve(session_id)
    except stripe.error.StripeError:
        logger.exception("Couldn't retrieve Checkout Session %s on success redirect", session_id)
        messages.error(request, "Couldn't confirm your payment — if you were charged, contact us.")
        return redirect("core:dashboard" if request.user.is_authenticated else "accounts:login")

    if upgrade.is_upgrade_session(session):
        # Basic -> Pro upgrade, not a normal signup — see apps.billing.upgrade
        # for the full migration this triggers. Same synchronous-path/webhook
        # dual-safety pattern as the normal signup flow below: whichever
        # fires first does the work, idempotently.
        try:
            upgrade.complete_upgrade_from_checkout_session(session)
        except Exception:
            logger.exception("Upgrade completion failed for Checkout Session %s", session_id)
            messages.error(
                request,
                "Payment went through, but we hit an issue finishing your upgrade. "
                "We've been notified and will follow up shortly — no need to try again.",
            )
            return redirect("core:dashboard" if request.user.is_authenticated else "accounts:login")
        return render(request, "billing/upgrade_success.html", {"pro_login_url": settings.PRO_APP_LOGIN_URL})

    subscription = services.link_subscription_from_checkout_session(session)
    if subscription is not None and subscription.has_access:
        messages.success(request, "You're all set — welcome to SiteRevive IQ.")
    else:
        messages.info(request, "Payment received — finishing setting up your account, this can take a few seconds.")
    return redirect("core:dashboard" if request.user.is_authenticated else "accounts:login")


def checkout_cancel(request):
    """
    Stripe redirects here if the customer backs out of Checkout (with
    ?interval= carried through from the signup view, so the retry
    button below doesn't need to ask again). The User/Workspace/
    Subscription(incomplete) rows created during signup are left in
    place on purpose — retry_checkout lets a now-logged-in user pick up
    right where they left off instead of registering again.
    """
    interval = request.GET.get("interval", "monthly")
    return render(request, "billing/checkout_cancel.html", {"interval": interval})


@login_required
@require_POST
def retry_checkout(request):
    """
    For a logged-in user whose workspace Subscription is still
    unlinked (e.g. they backed out of Checkout during signup, or their
    session expired before finishing) — creates a fresh Checkout
    Session for the same workspace without making them register again.
    """
    if not _is_workspace_owner(request):
        messages.error(request, "Only a workspace owner can manage billing.")
        return redirect("core:settings")

    subscription = getattr(request.workspace, "subscription", None)
    if subscription is None or subscription.is_linked:
        return redirect("core:dashboard")

    interval = request.POST.get("interval") or subscription.intended_interval or "monthly"

    success_url = request.build_absolute_uri(reverse("billing:checkout_success")) + "?session_id={CHECKOUT_SESSION_ID}"
    cancel_url = (
        request.build_absolute_uri(reverse("billing:checkout_cancel")) + f"?interval={interval}"
    )
    try:
        checkout_url = services.create_signup_checkout_session(
            subscription=subscription, user=request.user, interval=interval,
            success_url=success_url, cancel_url=cancel_url,
        )
    except (services.StripeNotConfiguredError, services.UnknownPriceError) as exc:
        messages.error(request, f"Couldn't start checkout: {exc}")
        return redirect("core:settings")
    return redirect(checkout_url)


@login_required
def upgrade_to_pro(request):
    """
    Settings -> "Upgrade to Pro". GET shows a confirmation page (what
    moves over, what doesn't, and that this is one-way); POST creates a
    real Stripe Checkout Session for a Pro subscription and sends the
    owner there. See apps.billing.upgrade for the full migration this
    triggers on success, and why it can live entirely in this codebase.
    """
    if not _is_workspace_owner(request):
        messages.error(request, "Only a workspace owner can upgrade this workspace.")
        return redirect("core:settings")

    workspace = request.workspace
    subscription = getattr(workspace, "subscription", None)

    if subscription is not None and subscription.is_migrated_to_pro:
        messages.info(request, "This workspace has already been upgraded to Pro.")
        return redirect("core:settings")

    if request.method == "POST":
        interval = request.POST.get("interval") or (
            subscription.intended_interval if subscription else ""
        ) or "monthly"
        if interval not in ("monthly", "annual"):
            interval = "monthly"

        try:
            upgrade.check_upgrade_eligibility(workspace)
        except upgrade.UpgradeError as exc:
            messages.error(request, str(exc))
            return redirect("core:settings")

        success_url = (
            request.build_absolute_uri(reverse("billing:checkout_success"))
            + "?session_id={CHECKOUT_SESSION_ID}"
        )
        cancel_url = request.build_absolute_uri(reverse("billing:upgrade_to_pro"))

        try:
            checkout_url = upgrade.create_upgrade_checkout_session(
                workspace=workspace, user=request.user, interval=interval,
                success_url=success_url, cancel_url=cancel_url,
            )
        except (services.StripeNotConfiguredError, upgrade.UnknownProPriceError) as exc:
            messages.error(request, f"Couldn't start the upgrade: {exc}")
            return redirect("core:settings")
        return redirect(checkout_url)

    interval = (subscription.intended_interval if subscription else "") or "monthly"
    return render(request, "billing/upgrade.html", {"interval": interval})


@login_required
@require_POST
def buy_credits(request):
    """
    Any workspace member can top up (not owner-gated like the
    subscription controls above) — running out of scan credits blocks
    everyone's work, not just billing admin, and this is a one-time
    purchase against CreditBalance rather than a change to the
    workspace's subscription itself.
    """
    if request.workspace is None:
        messages.error(request, "No workspace selected.")
        return redirect("core:settings")

    success_url = request.build_absolute_uri(reverse("billing:topup_success")) + "?session_id={CHECKOUT_SESSION_ID}"
    cancel_url = request.build_absolute_uri(reverse("core:settings"))
    try:
        checkout_url = services.create_topup_checkout_session(
            workspace=request.workspace, user=request.user,
            success_url=success_url, cancel_url=cancel_url,
        )
    except (services.StripeNotConfiguredError, services.UnknownPriceError) as exc:
        messages.error(request, f"Couldn't start checkout: {exc}")
        return redirect("core:settings")
    return redirect(checkout_url)


def topup_success(request):
    """
    Stripe redirects here after a successful top-up Checkout. Same
    synchronous-linking pattern as checkout_success above — grants the
    credits immediately rather than making the customer wait on webhook
    delivery, via link_credits_from_checkout_session (safe to also run
    again from the webhook).
    """
    session_id = request.GET.get("session_id")
    if not session_id:
        messages.error(request, "Missing checkout session — if you were charged, check Settings.")
        return redirect("core:dashboard" if request.user.is_authenticated else "accounts:login")

    try:
        client = services.build_client()
    except services.StripeNotConfiguredError:
        messages.error(request, "Billing isn't configured in this environment yet.")
        return redirect("core:dashboard" if request.user.is_authenticated else "accounts:login")

    try:
        session = client.v1.checkout.sessions.retrieve(session_id)
    except stripe.error.StripeError:
        logger.exception("Couldn't retrieve top-up Checkout Session %s on success redirect", session_id)
        messages.error(request, "Couldn't confirm your payment — if you were charged, contact us.")
        return redirect("core:dashboard" if request.user.is_authenticated else "accounts:login")

    if services.link_credits_from_checkout_session(session):
        messages.success(request, f"Added {settings.CREDIT_TOPUP_QUANTITY} scan credits to your workspace.")
    else:
        messages.info(request, "Payment received — finishing adding your credits, this can take a few seconds.")
    return redirect("core:settings" if request.user.is_authenticated else "accounts:login")


@login_required
@require_POST
def billing_portal(request):
    """
    Sends the workspace owner to Stripe's hosted Billing Portal to
    update their card, view invoices, or cancel. Owner-only, same as
    every other billing-adjacent control in Settings — and only usable
    once an operator has actually linked this workspace to a Stripe
    customer (see Subscription.is_linked).
    """
    if not _is_workspace_owner(request):
        messages.error(request, "Only a workspace owner can manage billing.")
        return redirect("core:settings")

    subscription = getattr(request.workspace, "subscription", None)
    if subscription is None or not subscription.is_linked:
        messages.error(
            request,
            "Billing isn't set up for this workspace yet — contact SiteRevive IQ to get it linked.",
        )
        return redirect("core:settings")

    return_url = request.build_absolute_uri(reverse("core:settings"))
    try:
        portal_url = services.create_billing_portal_session(subscription, return_url)
    except services.StripeNotConfiguredError:
        messages.error(request, "Billing isn't configured in this environment yet.")
        return redirect("core:settings")
    except stripe.error.StripeError as exc:
        logger.exception("Stripe billing portal session creation failed")
        messages.error(request, f"Couldn't open the billing portal: {exc.user_message or 'please try again.'}")
        return redirect("core:settings")

    return redirect(portal_url)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """
    Stripe calls this directly (no session, no CSRF token — hence the
    signature verification instead). Kept deliberately dumb: verify,
    hand off to services.handle_webhook_event, and return a status Stripe
    understands as "retry this" vs "done." See apps.billing.services for
    what actually happens to a Subscription row.
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error("Received a Stripe webhook but STRIPE_WEBHOOK_SECRET isn't configured.")
        return HttpResponse(status=503)

    try:
        client = services.build_client()
    except services.StripeNotConfiguredError:
        logger.error("Received a Stripe webhook but STRIPE_SECRET_KEY isn't configured.")
        return HttpResponse(status=503)

    try:
        event = client.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except ValueError:
        logger.warning("Stripe webhook: malformed payload")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        logger.warning("Stripe webhook: signature verification failed")
        return HttpResponse(status=400)

    try:
        services.handle_webhook_event(event, request)
    except Exception:
        # Non-2xx tells Stripe to retry with backoff — better than
        # silently swallowing a failed status update.
        logger.exception("Stripe webhook: failed to process event %s", getattr(event, "type", "unknown"))
        return HttpResponse(status=500)

    return HttpResponse(status=200)
