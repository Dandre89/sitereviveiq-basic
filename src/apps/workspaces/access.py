"""
Shared enforcement helpers, kept from the Enterprise build even though
the Pro build has no Viewer role or per-website access restriction —
CurrentWorkspaceMiddleware always sets request.can_edit=True and
request.accessible_website_ids=None here, which makes every function
below a permanent no-op. Left in place (rather than stripped out of
every view that calls them) so this file is the single place that
would need real logic again if per-website restriction ever comes
back to Pro — nothing else in the app needs to change.
"""
from functools import wraps

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect


def scope_websites(request, queryset, lookup="website_id"):
    """
    Filters a queryset down to rows whose website is in the caller's
    accessible set. No-op (returns queryset unchanged) for Owners and for
    any Member/Viewer who hasn't been restricted to specific websites —
    accessible_website_ids is None in both cases.

    `lookup` is the ORM field path to the website's id from this
    queryset's model, e.g. "pk" when the queryset IS Website, "website_id"
    for anything with a direct website FK, "roadmap__website_id" for
    RoadmapItem, "baseline__website_id", etc.
    """
    if request.accessible_website_ids is None:
        return queryset
    return queryset.filter(**{f"{lookup}__in": request.accessible_website_ids})


def require_website_access(request, website_id):
    """
    Raises Http404 (matching the existing get_object_or_404 pattern used
    everywhere else in this codebase — a restricted website should look
    like it doesn't exist, not like a permissions error, so it doesn't
    leak which websites exist in the workspace) if the caller is scoped
    to specific websites and this one isn't in the set.
    """
    if request.accessible_website_ids is not None and website_id not in request.accessible_website_ids:
        raise Http404("Website not found.")


def require_can_edit(view_func):
    """
    Blocks Viewers from reaching a mutating view. Stack this under
    @login_required (closest to the function) on every view that
    creates, updates, deletes, or triggers something — everything else
    (list/detail/export views) stays read-accessible to Viewers, gated
    only by require_website_access/scope_websites above.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.can_edit:
            messages.error(request, "Your role is view-only — ask a workspace owner for edit access.")
            referer = request.META.get("HTTP_REFERER")
            if referer:
                return redirect(referer)
            return redirect("core:dashboard")
        return view_func(request, *args, **kwargs)

    return wrapper
