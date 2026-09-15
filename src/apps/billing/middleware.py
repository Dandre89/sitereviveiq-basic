from django.conf import settings
from django.shortcuts import render

from .models import Subscription


class SubscriptionEnforcementMiddleware:
    """
    Blocks the app behind a "subscription inactive" page for any signed-in
    request against a workspace whose Subscription isn't active/trialing.
    Must sit after apps.workspaces.middleware.CurrentWorkspaceMiddleware in
    MIDDLEWARE — it reads request.workspace, which that middleware sets.

    Two deliberate scope limits, both worth knowing if this surprises you
    later:

    1. "Not configured in this environment" is a full no-op, not a soft
       warning. If settings.STRIPE_SECRET_KEY is blank — true for local/dev
       and for any environment that hasn't been wired up for real billing
       yet — this middleware does nothing at all, the same way EMAIL_HOST
       being unset falls back to the console email backend instead of
       failing. Flip STRIPE_SECRET_KEY on and enforcement turns on with it;
       nothing else has to change.

    2. Only signed-in, in-app requests are covered. Public share links
       (reports/proposals opened via an unguessable token, no login) never
       get a request.workspace from CurrentWorkspaceMiddleware in the first
       place, so they pass through untouched regardless of the owning
       workspace's billing state — deliberately out of scope for a first
       version, not an oversight.
    """

    # Paths that must stay reachable even for a blocked workspace — the
    # billing app itself (so a locked-out owner can still fix it), auth
    # (so they can log out), the Django admin (so an operator can always
    # get in), and static/media assets the locked page itself needs.
    EXEMPT_PREFIXES = ("/billing/", "/admin/", "/accounts/", "/static/", "/media/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_block(request):
            return render(
                request,
                "billing/locked.html",
                {
                    "subscription": getattr(request.workspace, "subscription", None),
                    "pro_app_login_url": settings.PRO_APP_LOGIN_URL,
                    "hide_chrome": True,
                },
                status=402,
            )
        return self.get_response(request)

    def _should_block(self, request) -> bool:
        if request.path.startswith(self.EXEMPT_PREFIXES):
            return False
        if not request.user.is_authenticated or request.workspace is None:
            return False
        if request.user.is_superuser:
            return False

        subscription = getattr(request.workspace, "subscription", None)

        # Checked before the STRIPE_SECRET_KEY escape hatch below: once a
        # workspace has been migrated to Pro (see apps.billing.upgrade)
        # it stays blocked here permanently, in every environment,
        # regardless of whether Stripe is configured — there's no
        # scenario where a migrated Basic account should still be usable.
        if subscription is not None and subscription.is_migrated_to_pro:
            return True

        if not settings.STRIPE_SECRET_KEY:
            return False

        if subscription is None:
            return True
        return subscription.status not in Subscription.ACCESS_GRANTING_STATUSES
