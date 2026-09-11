class CurrentWorkspaceMiddleware:
    """
    Attaches request.workspace for authenticated users so every view and
    queryset can filter by it without re-deriving membership each time.

    Also attaches the per-request permission surface used by
    apps.workspaces.access:
      - request.membership: the caller's WorkspaceMembership, or None.
      - request.can_edit: always True in the Pro build — Pro only has
        Owner/Member roles (no Viewer), so there's no read-only role to
        gate against. Kept as a real attribute (rather than removed
        outright) so apps.workspaces.access.require_can_edit and every
        view already decorated with it keep working unchanged.
      - request.accessible_website_ids: always None in the Pro build (no
        per-website access restriction — that's an Enterprise-only
        feature). None means "every website in the workspace" to
        apps.workspaces.access.scope_websites/require_website_access.

    Session timeout and per-device session tracking are Enterprise-only
    (see apps.accounts.models.UserSession in that build) — Pro just uses
    Django's default session behavior (SESSION_COOKIE_AGE).

    Build 1 assumption: one workspace per user (created by the admin
    bootstrap command). Multi-workspace switching is a SaaS-layer feature
    and is intentionally not built yet — see decisions log.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.workspace = None
        request.membership = None
        request.can_edit = True
        request.accessible_website_ids = None

        if request.user.is_authenticated:
            membership = (
                request.user.workspace_memberships.select_related("workspace")
                .filter(workspace__is_active=True)
                .first()
            )
            if membership:
                request.workspace = membership.workspace
                request.membership = membership
        return self.get_response(request)
