from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.accounts.forms import ProfileForm
from apps.accounts.models import UserNotificationPreference
from apps.core.emails import send_admin_notification
from apps.scans.models import Scan
from apps.websites.models import Website
from apps.workspaces.access import scope_websites
from apps.workspaces.models import WorkspaceMembership


def legal_terms(request):
    """Public — no @login_required. See views.py docstring note in the Enterprise codebase's copy of this page: policy text is company-wide and duplicated verbatim across all three tiers."""
    return render(request, "legal/terms.html")


def legal_privacy(request):
    return render(request, "legal/privacy.html")


def legal_refund_policy(request):
    return render(request, "legal/refund_policy.html")


def ratelimited(request, exception=None):
    """
    RATELIMIT_VIEW target (see settings) — called in place of the default
    403 whenever an @ratelimit-decorated view (login, password reset,
    signup) trips its limit. Always safe for an anonymous visitor: no
    workspace/user context required.
    """
    return render(request, "429.html", status=429)


@login_required
def dashboard(request):
    websites = scope_websites(request, Website.objects.filter(workspace=request.workspace), lookup="pk")
    scans = scope_websites(request, Scan.objects.filter(workspace=request.workspace))
    context = {
        "total_websites": websites.count(),
        "total_scans": scans.count(),
        "running_scans": scans.filter(status__in=Scan.ACTIVE_STATUSES).order_by("-created_at"),
        "recent_completed": scans.filter(status=Scan.Status.COMPLETED).order_by("-completed_at")[:10],
        "recent_failed": scans.filter(
            status__in=[Scan.Status.FAILED, Scan.Status.COMPLETED_WITH_ERRORS]
        ).order_by("-completed_at")[:10],
    }

    # --- Chart data ---
    # Scan status breakdown across every scan this workspace has run, grouped
    # into buckets a user actually cares about at a glance rather than all 8
    # raw Scan.Status values (the 4 in-flight statuses collapse into one
    # "In progress" slice — that granularity belongs to the running_scans
    # list above, not a summary chart).
    status_counts = {row["status"]: row["n"] for row in scans.values("status").annotate(n=Count("id"))}
    scan_status_chart = [
        {"label": "Completed", "count": status_counts.get(Scan.Status.COMPLETED, 0)},
        {"label": "Completed with errors", "count": status_counts.get(Scan.Status.COMPLETED_WITH_ERRORS, 0)},
        {"label": "Failed", "count": status_counts.get(Scan.Status.FAILED, 0)},
        {"label": "Cancelled", "count": status_counts.get(Scan.Status.CANCELLED, 0)},
        {"label": "In progress", "count": sum(status_counts.get(s, 0) for s in Scan.ACTIVE_STATUSES)},
    ]
    context["scan_status_chart"] = [row for row in scan_status_chart if row["count"]]

    # Website score overview: latest score per active website, worst-first.
    # Basic is capped at one website per workspace, so this will only ever
    # show a single bar — kept as a chart (not a stat card) anyway so the
    # visual stays consistent with Pro/Enterprise if that quota ever changes.
    scored_websites = (
        websites.exclude(status=Website.Status.ARCHIVED)
        .filter(last_scan__overall_score__isnull=False)
        .order_by("last_scan__overall_score")
        .values("name", "last_scan__overall_score")[:15]
    )
    context["website_score_chart"] = [
        {"label": w["name"], "score": w["last_scan__overall_score"]} for w in scored_websites
    ]

    return render(request, "dashboard/index.html", context)


def _get_credit_balance_for_display(workspace):
    """
    Read-only — never call apps.billing.credits.spend_credit or anything
    that mutates from here. Lazily creates a CreditBalance the first
    time a workspace is looked at (see get_or_create_balance's own
    docstring) so an older workspace that predates this feature still
    shows a real number instead of nothing.
    """
    from apps.billing.credits import get_or_create_balance

    return get_or_create_balance(workspace)


@login_required
def settings_view(request):
    is_owner = WorkspaceMembership.objects.filter(
        workspace=request.workspace, user=request.user, role=WorkspaceMembership.Role.OWNER
    ).exists()

    return render(
        request,
        "settings/index.html",
        {
            "profile_form": ProfileForm(instance=request.user),
            "is_workspace_owner": is_owner,
            "my_notification_preference": UserNotificationPreference.get_for_user(request.user),
            "subscription": getattr(request.workspace, "subscription", None) if request.workspace else None,
            "pro_app_login_url": settings.PRO_APP_LOGIN_URL,
            "credit_balance": (
                _get_credit_balance_for_display(request.workspace) if request.workspace else None
            ),
        },
    )


@login_required
@require_POST
def submit_feedback(request):
    """
    Backs the feedback tab in base.html (bottom-right, every authenticated
    page). Deliberately minimal — no FeedbackSubmission model, no admin
    console screen: it's just an admin_notification email to the team
    inbox with the message + who/where, same pattern as the new-signup
    pings in apps.accounts.views.signup. If we outgrow "read it in email"
    we can promote this to a real model later.
    """
    message = (request.POST.get("message") or "").strip()
    if not message:
        return render(request, "core/_feedback_result.html", {"error": True})

    workspace = getattr(request, "workspace", None)
    page_url = request.POST.get("page_url") or request.META.get("HTTP_REFERER", "—")
    send_admin_notification(
        subject=f"Feedback from {request.user.email}",
        body=(
            f"{request.user.first_name} ({request.user.email}) sent feedback:\n\n"
            f"{message}\n\n"
            f"Workspace: {workspace.name if workspace else '—'}\n"
            f"Page: {page_url}\n"
            f"App version: {settings.APP_VERSION}"
        ),
    )
    return render(request, "core/_feedback_result.html", {"error": False})
