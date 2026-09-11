from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.sorting import resolve_sort
from apps.findings.models import BASIC_ISSUE_CATEGORIES, Issue
from apps.findings.ordering import PRIORITY_RANK, SEVERITY_RANK
from apps.scans.models import Scan, ScanPage
from apps.scans.services import DuplicateActiveScanError, start_scan
from apps.scans.tasks import run_scan_task
from apps.workspaces.access import require_can_edit, require_website_access, scope_websites

from .forms import WebsiteForm
from .models import Website

WEBSITE_SORT_FIELDS = {
    "name": "name",
    "type": "website_type",
    "status": "status",
    "score": "last_scan__overall_score",
    "last_scan": "last_scan__created_at",
}

PRIORITY_ORDER = {
    Issue.PriorityClass.IMMEDIATE_RISK: 0,
    Issue.PriorityClass.QUICK_WIN: 1,
    Issue.PriorityClass.GROWTH_IMPROVEMENT: 2,
    Issue.PriorityClass.STRATEGIC_RENOVATION: 3,
    "": 4,
}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

ISSUE_SORT_FIELDS = {
    "title": "title",
    "priority": "priority_rank",
    "severity": "severity_rank",
    "category": "category",
    "where": "affected_scope",
}
PAGE_SORT_FIELDS = {
    "url": "normalized_url",
    "status": "fetch_status",
    "title": "page_title",
    "words": "word_count",
    "depth": "crawl_depth",
}
SCAN_SORT_FIELDS = {
    "date": "created_at",
    "status": "status",
    "completed": "pages_completed",
    "failed": "pages_failed",
    "requested_by": "requested_by__email",
}


@login_required
def website_list(request):
    websites = scope_websites(
        request, Website.objects.filter(workspace=request.workspace), lookup="pk"
    ).select_related("last_scan")

    website_type = request.GET.get("type", "")
    status = request.GET.get("status", "")
    if website_type:
        websites = websites.filter(website_type=website_type)
    if status:
        websites = websites.filter(status=status)

    order_by, sort_key, direction = resolve_sort(request, WEBSITE_SORT_FIELDS, default_key="name")
    websites = websites.order_by(order_by)

    return render(
        request,
        "websites/list.html",
        {
            "websites": websites,
            "website_types": Website.WebsiteType.choices,
            "statuses": Website.Status.choices,
            "selected_type": website_type,
            "selected_status": status,
        },
    )


# The one quota this tier enforces now rather than deferring — "one
# site" isn't a soft capacity limit, it's the defining structural trait
# of this tier, so leaving it unenforced would let the Basic/Pro
# boundary quietly stop meaning anything before any billing system
# exists to charge for the difference.
MAX_WEBSITES = 1


@login_required
@require_can_edit
def website_add(request):
    at_limit = Website.objects.filter(workspace=request.workspace).count() >= MAX_WEBSITES
    if at_limit:
        messages.error(
            request,
            f"This plan tracks {MAX_WEBSITES} website. Remove the existing one to add a different site.",
        )
        return redirect("websites:list")

    if request.method == "POST":
        form = WebsiteForm(request.POST)
        if form.is_valid():
            website = form.save(commit=False)
            website.workspace = request.workspace
            website.created_by = request.user
            website.save()
            messages.success(request, f"Added {website.name}.")
            return redirect("websites:detail", pk=website.pk)
    else:
        form = WebsiteForm()
    return render(request, "websites/form.html", {"form": form, "mode": "add"})


@login_required
@require_can_edit
def website_edit(request, pk):
    website = get_object_or_404(Website, pk=pk, workspace=request.workspace)
    require_website_access(request, website.pk)
    if request.method == "POST":
        form = WebsiteForm(request.POST, instance=website)
        if form.is_valid():
            form.save()
            messages.success(request, f"Updated {website.name}.")
            return redirect("websites:detail", pk=website.pk)
    else:
        form = WebsiteForm(instance=website)
    return render(request, "websites/form.html", {"form": form, "mode": "edit", "website": website})


@login_required
def website_detail(request, pk):
    website = get_object_or_404(Website, pk=pk, workspace=request.workspace)
    require_website_access(request, website.pk)

    # --- Open issues: filter + sort ---
    issues = Issue.objects.filter(website=website, status=Issue.Status.OPEN).annotate(
        priority_rank=PRIORITY_RANK, severity_rank=SEVERITY_RANK
    )
    issue_category = request.GET.get("icategory", "")
    issue_severity = request.GET.get("iseverity", "")
    if issue_category:
        issues = issues.filter(category=issue_category)
    if issue_severity:
        issues = issues.filter(current_severity=issue_severity)
    issue_order, issue_sort_key, issue_dir = resolve_sort(
        request, ISSUE_SORT_FIELDS, default_key="priority", sort_param="isort", dir_param="idir"
    )
    issue_order_fields = [issue_order]
    if issue_sort_key == "priority":
        issue_order_fields.append("severity_rank" if issue_dir == "asc" else "-severity_rank")
    issues = issues.order_by(*issue_order_fields)

    # --- Pages (most recent scan): filter + sort ---
    pages = ScanPage.objects.none()
    page_status = request.GET.get("pstatus", "")
    if website.last_scan_id:
        pages = website.last_scan.pages.all()
        if page_status:
            pages = pages.filter(fetch_status=page_status)
        page_order, page_sort_key, _ = resolve_sort(
            request, PAGE_SORT_FIELDS, default_key="depth", sort_param="psort", dir_param="pdir"
        )
        if page_sort_key == "depth":
            pages = pages.order_by(page_order, "normalized_url")
        else:
            pages = pages.order_by(page_order)
        pages = pages[:100]

    # --- Scan history: filter + sort ---
    scans = website.scans.all()
    scan_status = request.GET.get("sstatus", "")
    if scan_status:
        scans = scans.filter(status=scan_status)
    scan_order, scan_sort_key, _ = resolve_sort(
        request, SCAN_SORT_FIELDS, default_key="date", sort_param="ssort", dir_param="sdir"
    )
    if scan_sort_key == "date":
        scans = scans.order_by(scan_order)
    else:
        scans = scans.order_by(scan_order, "-created_at")
    scans = scans[:20]


    avg_response_ms = None
    avg_page_weight_bytes = None
    if website.last_scan_id:
        completed_pages = website.last_scan.pages.filter(fetch_status=ScanPage.FetchStatus.COMPLETED)
        aggregates = completed_pages.aggregate(
            avg_response_ms=Avg("response_time_ms"),
            avg_page_weight_bytes=Avg("response_size_bytes"),
        )
        avg_response_ms = aggregates["avg_response_ms"]
        avg_page_weight_bytes = aggregates["avg_page_weight_bytes"]

    # --- Chart data ---
    # Category scores: only assessed categories (not_yet_assessed ones are
    # excluded, same rule the overall score itself uses — showing a 0 here
    # would misrepresent an un-scanned category as a failing one). Basic's
    # analyzer.scoring only ever populates the 4 categories this tier
    # tracks, so this naturally comes out narrower than Pro/Enterprise
    # without any tier-specific branching needed here.
    category_labels = dict(BASIC_ISSUE_CATEGORIES)
    category_chart = []
    if website.last_scan_id and website.last_scan.category_scores:
        for key, entry in website.last_scan.category_scores.items():
            if entry.get("assessed") and entry.get("score") is not None:
                category_chart.append({"label": category_labels.get(key, key), "score": entry["score"]})

    # Score trend: last 10 completed scans with a real score, oldest first
    # so the line reads left-to-right chronologically.
    trend_scans = list(
        website.scans.filter(
            status__in=[Scan.Status.COMPLETED, Scan.Status.COMPLETED_WITH_ERRORS],
            overall_score__isnull=False,
        ).order_by("-created_at")[:10]
    )
    trend_scans.reverse()
    score_trend = [
        {"date": timezone.localtime(s.created_at).strftime("%b %-d"), "score": s.overall_score}
        for s in trend_scans
    ]

    # Open-issue breakdowns: computed off the FULL open-issue set for this
    # website, independent of whatever filter is applied to the table below
    # — the chart should always summarize everything, not just what's shown.
    all_open_issues = Issue.objects.filter(website=website, status=Issue.Status.OPEN)
    severity_labels = dict(Issue.Severity.choices)
    severity_counts = {k: 0 for k in severity_labels}
    for row in all_open_issues.values("current_severity").annotate(n=Count("id")):
        if row["current_severity"] in severity_counts:
            severity_counts[row["current_severity"]] = row["n"]
    issues_by_severity = [
        {"label": severity_labels[k], "count": v} for k, v in severity_counts.items() if v
    ]

    category_counts = {}
    for row in all_open_issues.values("category").annotate(n=Count("id")):
        category_counts[row["category"]] = row["n"]
    issues_by_category = [
        {"label": category_labels.get(k, k), "count": v} for k, v in category_counts.items() if v
    ]

    return render(
        request,
        "websites/detail.html",
        {
            "website": website,
            "scans": scans,
            "pages": pages,
            "issues": issues,
            "issue_categories": BASIC_ISSUE_CATEGORIES,
            "issue_severities": Issue.Severity.choices,
            "selected_icategory": issue_category,
            "selected_iseverity": issue_severity,
            "page_statuses": ScanPage.FetchStatus.choices,
            "selected_pstatus": page_status,
            "scan_statuses": Scan.Status.choices,
            "selected_sstatus": scan_status,
            "avg_response_ms": avg_response_ms,
            "avg_page_weight_bytes": avg_page_weight_bytes,
            "avg_page_weight_mb": (avg_page_weight_bytes / 1048576) if avg_page_weight_bytes else None,
            "category_chart": category_chart,
            "score_trend": score_trend,
            "issues_by_severity": issues_by_severity,
            "issues_by_category": issues_by_category,
        },
    )


@login_required
@require_can_edit
def website_archive(request, pk):
    website = get_object_or_404(Website, pk=pk, workspace=request.workspace)
    require_website_access(request, website.pk)
    if request.method == "POST":
        website.status = Website.Status.ARCHIVED
        website.save(update_fields=["status"])
        messages.success(request, f"Archived {website.name}.")
    return redirect("websites:detail", pk=website.pk)


@login_required
@require_can_edit
def website_unarchive(request, pk):
    website = get_object_or_404(Website, pk=pk, workspace=request.workspace)
    require_website_access(request, website.pk)
    if request.method == "POST":
        website.status = Website.Status.ACTIVE
        website.save(update_fields=["status"])
        messages.success(request, f"Unarchived {website.name}.")
    return redirect("websites:detail", pk=website.pk)


@login_required
@require_can_edit
def website_run_scan(request, pk):
    website = get_object_or_404(Website, pk=pk, workspace=request.workspace)
    # Reachable with a competitor row's pk too (from competitor_detail's
    # "Scan now" button) — competitor rows aren't in anyone's WebsiteAccess
    # set, so access follows the primary site they're tracked against.
    require_website_access(request, website.tracks_competitor_for_id or website.pk)
    if request.method != "POST":
        return redirect("websites:detail", pk=website.pk)

    if website.status == Website.Status.ARCHIVED:
        messages.error(request, "Archived websites cannot be scanned.")
        return redirect("websites:detail", pk=website.pk)

    try:
        scan = start_scan(website, requested_by=request.user, trigger=Scan.Trigger.MANUAL)
    except DuplicateActiveScanError:
        messages.error(request, "This website already has a scan in progress.")
        return redirect("websites:detail", pk=website.pk)

    task = run_scan_task.delay(str(scan.id))
    scan.celery_task_id = task.id
    scan.save(update_fields=["celery_task_id"])

    return redirect("scans:progress", pk=scan.pk)
