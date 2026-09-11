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

from . import services

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
        services.handle_webhook_event(event)
    except Exception:
        # Non-2xx tells Stripe to retry with backoff — better than
        # silently swallowing a failed status update.
        logger.exception("Stripe webhook: failed to process event %s", getattr(event, "type", "unknown"))
        return HttpResponse(status=500)

    return HttpResponse(status=200)
