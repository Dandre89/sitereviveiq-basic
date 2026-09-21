import json
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, PasswordResetForm
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.billing import services as billing_services
from apps.billing.models import Subscription
from apps.core.emails import send_templated_email
from apps.workspaces.models import AuditLogEntry, Workspace, WorkspaceMembership

from .forms import AccountDeletionForm, ProfileForm, SignupForm
from .models import User, UserNotificationPreference

NOTIFICATION_PREFERENCE_FIELDS = [
    "notify_critical_findings",
    "notify_score_drops",
    "notify_scan_completed",
    "notify_new_opportunities",
    "notify_returning_issues",
    "notify_credits_exhausted",
    "notify_proposal_response",
]


def send_welcome_email(user, request) -> None:
    """Fired the moment a new user account exists — self-serve signup
    below is the only path that creates one in this single-workspace
    build (no team invites in Basic)."""
    send_templated_email(
        template_name="welcome",
        context={
            "first_name": user.first_name,
            "dashboard_url": request.build_absolute_uri(reverse("core:dashboard")),
        },
        subject="Welcome to SiteRevive IQ",
        to=[user.email],
    )


def send_password_changed_email(user) -> None:
    """
    Security confirmation sent any time a password successfully changes —
    from the in-app change-password form (change_password below) or from
    completing the forgot-password reset flow (PasswordChangedConfirmView
    below). Never gated by notification preferences: this one's mandatory.
    """
    send_templated_email(
        template_name="password_changed",
        context={"first_name": user.first_name, "email": user.email},
        subject="Your SiteRevive IQ password was changed",
        to=[user.email],
    )


class PasswordChangedConfirmView(auth_views.PasswordResetConfirmView):
    """Same reset-confirm flow as Django's own view — the only addition is
    firing the security confirmation email once the new password is saved."""

    def form_valid(self, form):
        response = super().form_valid(form)
        send_password_changed_email(form.user)
        return response


def send_account_deletion_requested_email(user, workspace) -> None:
    """Confirmation sent the moment the workspace owner requests self-serve
    deletion (request_account_deletion below) — reassures them nothing's
    gone yet and tells them how to back out before the billing period ends."""
    send_templated_email(
        template_name="account_deletion_requested",
        context={"first_name": user.first_name, "workspace_name": workspace.name},
        subject="Your SiteRevive IQ account is scheduled for deletion",
        to=[user.email],
    )


def _unique_workspace_slug(name: str) -> str:
    base = slugify(name) or "workspace"
    slug = base
    suffix = 1
    while Workspace.objects.filter(slug=slug).exists():
        suffix += 1
        slug = f"{base}-{suffix}"
    return slug


def signup(request):
    """
    Public, unauthenticated entry point for self-serve checkout. This
    build only ever sells Basic (no Pro/Enterprise plan selector here —
    contrast with the Pro codebase's version of this view), just a
    Monthly/Annual interval choice. Creates the User + Workspace + an
    "incomplete" Subscription row in one transaction, logs the user in,
    then sends them straight to a real Stripe Checkout Session — charged
    immediately, no trial (see apps.billing.services.create_signup_checkout_session).
    Nothing here grants product access by itself — the workspace stays
    blocked by SubscriptionEnforcementMiddleware until
    apps.billing.services.link_subscription_from_checkout_session runs,
    either from the synchronous checkout_success view or the
    checkout.session.completed webhook (whichever lands first).
    """
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    interval = request.GET.get("interval") or request.POST.get("interval") or "monthly"
    if interval not in ("monthly", "annual"):
        interval = "monthly"

    form = SignupForm(request.POST or None)

    if request.method == "POST":
        try:
            billing_services.get_price_id(interval)
        except billing_services.UnknownPriceError:
            messages.error(
                request,
                "Online checkout isn't available right now — please contact us instead.",
            )
            return render(request, "billing/signup.html", {"form": form, "interval": interval})

        if form.is_valid():
            with transaction.atomic():
                user = User.objects.create_user(
                    email=form.cleaned_data["email"],
                    password=form.cleaned_data["password"],
                    first_name=form.cleaned_data["full_name"],
                )
                workspace_name = form.cleaned_data["workspace_name"]
                workspace = Workspace.objects.create(
                    name=workspace_name, slug=_unique_workspace_slug(workspace_name)
                )
                WorkspaceMembership.objects.create(
                    workspace=workspace, user=user, role=WorkspaceMembership.Role.OWNER
                )
                subscription = Subscription.objects.create(
                    workspace=workspace, intended_interval=interval
                )

            login(request, user)
            send_welcome_email(user, request)

            success_url = (
                request.build_absolute_uri(reverse("billing:checkout_success"))
                + "?session_id={CHECKOUT_SESSION_ID}"
            )
            cancel_url = (
                request.build_absolute_uri(reverse("billing:checkout_cancel"))
                + f"?interval={interval}"
            )
            try:
                checkout_url = billing_services.create_signup_checkout_session(
                    subscription=subscription,
                    user=user,
                    interval=interval,
                    success_url=success_url,
                    cancel_url=cancel_url,
                )
            except billing_services.StripeNotConfiguredError:
                messages.error(request, "Billing isn't configured in this environment yet.")
                return redirect("core:dashboard")
            return redirect(checkout_url)

    return render(request, "billing/signup.html", {"form": form, "interval": interval})


@login_required
def update_profile(request):
    if request.method != "POST":
        return redirect("core:settings")

    form = ProfileForm(request.POST, instance=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
    return redirect("core:settings")


@login_required
def change_password(request):
    if request.method != "POST":
        return redirect("core:settings")

    form = PasswordChangeForm(user=request.user, data=request.POST)
    if form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)  # keep the session valid after changing the password
        send_password_changed_email(user)
        messages.success(request, "Password changed.")
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
    return redirect("core:settings")


@login_required
def update_my_notification_preferences(request):
    """
    Per-user opt-out for the monitoring-style emails (scan completed,
    critical finding, credits exhausted, etc.) — separate from, and on
    top of, the per-workspace toggle every owner controls in
    apps.workspaces.views.update_notifications. Every checkbox defaults
    unchecked when *absent* from POST, so an unchecked box correctly
    turns a category off rather than leaving it untouched.
    """
    if request.method != "POST":
        return redirect("core:settings")

    pref = UserNotificationPreference.get_for_user(request.user)
    for field_name in NOTIFICATION_PREFERENCE_FIELDS:
        setattr(pref, field_name, field_name in request.POST)
    pref.save()
    messages.success(request, "Your notification preferences were saved.")
    return redirect("core:settings")


@login_required
@require_POST
def request_account_deletion(request):
    """
    Self-serve account deletion. Only a workspace owner can trigger this.

    This does NOT delete any data. It's a soft, staff-reversible
    "pending" flag: Stripe is set to stop renewing at the end of the
    current paid period (no proration, no refund — see
    billing.services.cancel_subscription_at_period_end), and the
    workspace is marked owner_deleted. Access continues completely
    normally until the paid period actually runs out — cutoff happens
    on its own via SubscriptionEnforcementMiddleware once Stripe's
    webhook reports the subscription has lapsed. The workspace and
    everything in it stay fully intact in the database until a staff
    member performs the separate, irreversible permanent-purge action
    in the admin console.
    """
    membership = WorkspaceMembership.objects.filter(
        workspace=request.workspace, user=request.user
    ).first()
    if membership is None or membership.role != WorkspaceMembership.Role.OWNER:
        messages.error(request, "Only the workspace owner can delete this account.")
        return redirect("core:settings")

    form = AccountDeletionForm(request.POST, user=request.user)
    if not form.is_valid():
        messages.error(request, "That password isn't correct — account not deleted.")
        return redirect("core:settings")

    workspace = request.workspace
    subscription = getattr(workspace, "subscription", None)
    if subscription is not None:
        try:
            billing_services.cancel_subscription_at_period_end(subscription)
        except billing_services.StripeNotConfiguredError:
            pass  # local/dev environment — nothing to cancel, just proceed with flagging the workspace

    workspace.lifecycle_status = Workspace.LifecycleStatus.OWNER_DELETED
    workspace.deletion_requested_at = timezone.now()
    workspace.deletion_requested_by = request.user
    workspace.save(update_fields=["lifecycle_status", "deletion_requested_at", "deletion_requested_by"])

    AuditLogEntry.objects.create(
        workspace=workspace,
        actor=request.user,
        action=AuditLogEntry.Action.DELETION_REQUESTED,
        description=f"{request.user.email} requested account deletion.",
    )
    send_account_deletion_requested_email(request.user, workspace)

    messages.success(
        request,
        "Your account is scheduled for deletion. You'll keep full access until your "
        "current billing period ends, then you'll be signed out automatically. "
        "Contact us before then if you change your mind.",
    )
    return redirect("core:settings")


# --- Internal admin console integration ---
#
# The internal admin console (a separate project — see its own README)
# needs to be able to trigger the exact same password-reset email flow
# a customer would trigger themselves at accounts:password_reset,
# rather than the console minting its own token or setting a password
# directly. Routing it through PasswordResetForm here means both paths
# share one implementation of "how a reset link gets made and sent" —
# there's no second, differently-secured way to end up with a valid
# reset link for someone's account.
#
# Auth is a single shared bearer token (INTERNAL_API_TOKEN), not a user
# session — this is a server-to-server call from the console's backend,
# never from a browser, hence @csrf_exempt. secrets.compare_digest
# avoids a timing side-channel on the comparison.

@csrf_exempt
@require_POST
def internal_trigger_password_reset(request):
    if not settings.INTERNAL_API_TOKEN:
        return HttpResponseForbidden("Internal API not configured.")

    auth_header = request.headers.get("Authorization", "")
    provided = auth_header.removeprefix("Bearer ").strip()
    if not provided or not secrets.compare_digest(provided, settings.INTERNAL_API_TOKEN):
        return HttpResponseForbidden("Invalid or missing token.")

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    email = (payload.get("email") or "").strip().lower()
    if not email:
        return JsonResponse({"error": "email is required."}, status=400)

    UserModel = get_user_model()
    user_exists = UserModel.objects.filter(email=email, is_active=True).exists()

    if user_exists:
        form = PasswordResetForm(data={"email": email})
        if form.is_valid():
            form.save(
                email_template_name="registration/password_reset_email.html",
                subject_template_name="registration/password_reset_subject.txt",
                request=request,
            )

    # Always returns the same shape whether or not the account exists —
    # matches the self-service form's own "check your email" behavior,
    # so this endpoint can't be used to enumerate which emails have
    # accounts on this tier.
    return JsonResponse({"status": "ok"})


@csrf_exempt
@require_POST
def internal_create_account(request):
    """Admin-console-driven Basic account provisioning for sales-assisted /
    manual signups (a deal that didn't go through self-serve Stripe
    Checkout). Mirrors the self-serve signup view's create-user +
    Workspace + WorkspaceMembership(OWNER) + Subscription sequence, minus
    the parts that only make sense mid-checkout (no password from the
    customer, no intended_plan/interval). Reachable from the console over
    the same Bearer-token internal-API pattern as
    internal_trigger_password_reset above, instead of the customer's own
    browser. The new owner has no password yet; we email them a normal
    password-reset link (same flow self-service "forgot password" uses)
    so they set their own, plus the standard welcome email.
    """
    if not settings.INTERNAL_API_TOKEN:
        return HttpResponseForbidden("Internal API not configured.")

    auth_header = request.headers.get("Authorization", "")
    provided = auth_header.removeprefix("Bearer ").strip()
    if not provided or not secrets.compare_digest(provided, settings.INTERNAL_API_TOKEN):
        return HttpResponseForbidden("Invalid or missing token.")

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    email = (payload.get("email") or "").strip().lower()
    workspace_name = (payload.get("workspace_name") or "").strip()
    first_name = (payload.get("first_name") or "").strip()
    last_name = (payload.get("last_name") or "").strip()

    if not email or not workspace_name:
        return JsonResponse({"error": "email and workspace_name are required."}, status=400)

    from django.db import transaction

    from apps.billing.models import Subscription
    from apps.workspaces.models import Workspace, WorkspaceMembership

    UserModel = get_user_model()
    if UserModel.objects.filter(email=email).exists():
        return JsonResponse({"error": f"A user with email {email} already exists."}, status=409)

    with transaction.atomic():
        user = UserModel.objects.create_user(
            email=email, password=None, first_name=first_name,
        )
        workspace = Workspace.objects.create(
            name=workspace_name, slug=_unique_workspace_slug(workspace_name)
        )
        WorkspaceMembership.objects.create(
            workspace=workspace, user=user, role=WorkspaceMembership.Role.OWNER,
        )
        Subscription.objects.create(workspace=workspace)

    send_welcome_email(user, request)

    reset_form = PasswordResetForm(data={"email": email})
    if reset_form.is_valid():
        reset_form.save(
            email_template_name="registration/password_reset_email.txt",
            html_email_template_name="registration/password_reset_email.html",
            subject_template_name="registration/password_reset_subject.txt",
            request=request,
        )

    return JsonResponse(
        {"status": "ok", "user_id": str(user.id), "workspace_id": str(workspace.id)}
    )
