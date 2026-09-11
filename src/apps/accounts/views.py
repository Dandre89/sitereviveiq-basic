from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.text import slugify

from apps.billing import services as billing_services
from apps.billing.models import Subscription
from apps.workspaces.models import Workspace, WorkspaceMembership

from .forms import ProfileForm, SignupForm
from .models import User


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
        messages.success(request, "Password changed.")
    else:
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
    return redirect("core:settings")
