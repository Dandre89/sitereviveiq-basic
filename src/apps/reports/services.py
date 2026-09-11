"""
Report generation per spec 8.6. Deliberately reuses Build 3 (scores)
data rather than recomputing anything — a report is a formatted view
over work those builds already did.

This build only generates the Prospect Audit report type — Client
Health and Renovation Results both need an active Baseline to compare
against, and the Renovation Proposal generator needs a Roadmap; both
Baselines and Roadmap are Pro+ features not present here.

Not built here (see conversation notes): PDF export and styled
"branded" web templates — both are visual/UI work bundled into the
deferred UI pass, along with the Dockerfile changes PDF rendering
would need. This module only produces the structured content those
renderers will eventually read.
"""
from django.utils import timezone

from apps.findings.models import Issue

from .models import Report, ReportShareLink

PRIORITY_ORDER = {
    Issue.PriorityClass.IMMEDIATE_RISK: 0,
    Issue.PriorityClass.QUICK_WIN: 1,
    Issue.PriorityClass.GROWTH_IMPROVEMENT: 2,
    Issue.PriorityClass.STRATEGIC_RENOVATION: 3,
    "": 4,
}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _issue_summary(issue: Issue) -> dict:
    return {
        "id": str(issue.id),
        "title": issue.title,
        "category": issue.category,
        "severity": issue.current_severity,
        "priority_class": issue.priority_class,
        "affected_scope": issue.affected_scope,
        "recommendation": issue.recommendation,
    }


def _top_open_issues(website, limit: int = 10) -> list[dict]:
    issues = list(Issue.objects.filter(website=website, status=Issue.Status.OPEN))
    issues.sort(
        key=lambda i: (
            PRIORITY_ORDER.get(i.priority_class, 4),
            SEVERITY_ORDER.get(i.current_severity, 4),
        )
    )
    return [_issue_summary(i) for i in issues[:limit]]


def generate_prospect_audit(website, scan, generated_by=None) -> Report:
    """Spec 8.6: executive summary, health overview, top opportunities,
    competitive weaknesses, evidence, next step."""
    top_opportunities = _top_open_issues(website)

    content = {
        "executive_summary": (
            f"{website.name} currently scores {scan.overall_score if scan.overall_score is not None else 'N/A'}/100 "
            f"overall, with {len(top_opportunities)} priority opportunities identified across the site."
        ),
        "health_overview": {
            "overall_score": scan.overall_score,
            "category_scores": scan.category_scores,
        },
        "top_opportunities": top_opportunities,
        "competitive_weaknesses": {
            "assessed": False,
            "note": "Competitive analysis is not part of this plan.",
        },
        "next_step": "Review the top opportunities above and plan next steps for addressing them.",
    }

    return Report.objects.create(
        workspace=website.workspace,
        website=website,
        report_type=Report.ReportType.PROSPECT_AUDIT,
        title=f"{website.name} — Prospect Audit",
        scan=scan,
        content=content,
        generated_by=generated_by,
    )


def create_share_link(report: Report, expires_at=None, created_by=None) -> ReportShareLink:
    return ReportShareLink.objects.create(
        report=report, expires_at=expires_at, created_by=created_by
    )


def get_or_create_report_share_link(report: Report, created_by=None) -> ReportShareLink:
    """Reuses the most recent still-valid link instead of minting a new token every click."""
    existing = report.share_links.filter(revoked=False).order_by("-created_at").first()
    if existing and existing.is_valid():
        return existing
    return create_share_link(report, created_by=created_by)


def revoke_report_share_links(report: Report) -> None:
    report.share_links.filter(revoked=False).update(revoked=True)


def record_share_link_view(share_link: ReportShareLink) -> None:
    share_link.view_count += 1
    share_link.last_viewed_at = timezone.now()
    share_link.save(update_fields=["view_count", "last_viewed_at"])
