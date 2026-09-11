from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.sorting import resolve_sort
from apps.websites.models import Website
from apps.workspaces.access import require_can_edit, require_website_access, scope_websites

from .fixes import generate_fix
from .models import BASIC_ISSUE_CATEGORIES, Issue
from .ordering import PRIORITY_RANK, SEVERITY_RANK

ISSUE_SORT_FIELDS = {
    "title": "title",
    "website": "website__name",
    "priority": "priority_rank",
    "severity": "severity_rank",
    "category": "category",
    "status": "status",
    "where": "affected_scope",
}


@login_required
def issue_inbox(request):
    issues = scope_websites(
        request,
        Issue.objects.filter(workspace=request.workspace)
        .select_related("website")
        .annotate(priority_rank=PRIORITY_RANK, severity_rank=SEVERITY_RANK),
    )

    website_id = request.GET.get("website", "")
    category = request.GET.get("category", "")
    severity = request.GET.get("severity", "")
    status = request.GET.get("status", Issue.Status.OPEN)

    if website_id:
        issues = issues.filter(website_id=website_id)
    if category:
        issues = issues.filter(category=category)
    if severity:
        issues = issues.filter(current_severity=severity)
    if status:
        issues = issues.filter(status=status)

    # --- Chart data: aggregated off the currently filtered set, before
    # table ordering is applied, so the breakdown always matches what the
    # filters above are showing (not the full unfiltered inbox). ---
    category_labels = dict(BASIC_ISSUE_CATEGORIES)
    severity_labels = dict(Issue.Severity.choices)
    category_counts = {row["category"]: row["n"] for row in issues.values("category").annotate(n=Count("id"))}
    issues_by_category = [
        {"label": category_labels.get(k, k), "count": v} for k, v in category_counts.items() if v
    ]
    severity_counts = {
        row["current_severity"]: row["n"] for row in issues.values("current_severity").annotate(n=Count("id"))
    }
    issues_by_severity = [
        {"label": severity_labels.get(k, k), "count": v} for k, v in severity_counts.items() if v
    ]

    order_by, sort_key, direction = resolve_sort(request, ISSUE_SORT_FIELDS, default_key="priority")
    order_fields = [order_by]
    if sort_key == "priority":
        order_fields.append("severity_rank" if direction == "asc" else "-severity_rank")
    issues = issues.order_by(*order_fields)

    websites = scope_websites(
        request, Website.objects.filter(workspace=request.workspace), lookup="pk"
    ).order_by("name")

    return render(
        request,
        "findings/issue_inbox.html",
        {
            "issues": issues,
            "websites": websites,
            "categories": BASIC_ISSUE_CATEGORIES,
            "severities": Issue.Severity.choices,
            "statuses": Issue.Status.choices,
            "selected_website": website_id,
            "selected_category": category,
            "selected_severity": severity,
            "selected_status": status,
            "issues_by_category": issues_by_category,
            "issues_by_severity": issues_by_severity,
        },
    )


@login_required
def issue_detail(request, pk):
    issue = get_object_or_404(
        Issue.objects.select_related("website"), pk=pk, workspace=request.workspace
    )
    require_website_access(request, issue.website_id)
    fix = generate_fix(issue)
    return render(
        request,
        "findings/issue_detail.html",
        {
            "issue": issue,
            "fix": fix,
            "statuses": Issue.Status.choices,
        },
    )


@login_required
@require_can_edit
def issue_update_status(request, pk):
    issue = get_object_or_404(Issue, pk=pk, workspace=request.workspace)
    require_website_access(request, issue.website_id)
    if request.method != "POST":
        return redirect("findings:detail", pk=issue.pk)

    new_status = request.POST.get("status")
    if new_status not in Issue.Status.values:
        messages.error(request, "Unknown status.")
        return redirect("findings:detail", pk=issue.pk)

    issue.status = new_status
    issue.ignored_reason = request.POST.get("ignored_reason", "").strip() if new_status == Issue.Status.IGNORED else ""
    issue.resolved_at = timezone.now() if new_status == Issue.Status.RESOLVED else None
    issue.save(update_fields=["status", "ignored_reason", "resolved_at"])
    messages.success(request, f"Marked “{issue.title}” as {issue.get_status_display()}.")
    return redirect("findings:detail", pk=issue.pk)
