import pytest

from apps.comparisons.models import Baseline, Comparison
from apps.findings.models import Issue
from apps.reports.models import Report
from apps.reports.services import (
    create_share_link,
    generate_client_health_report,
    generate_prospect_audit,
    generate_proposal_draft,
    generate_renovation_results_report,
)
from apps.roadmaps.models import RoadmapItem
from apps.roadmaps.services import add_manual_item, create_roadmap
from apps.scans.models import Scan
from apps.websites.models import Website
from apps.workspaces.models import Workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def workspace():
    return Workspace.objects.create(name="Test Workspace")


@pytest.fixture
def website(workspace):
    return Website.objects.create(
        workspace=workspace,
        name="Test Site",
        submitted_url="https://example.com/",
        canonical_url="https://example.com/",
        normalized_host="example.com",
    )


def make_scan(workspace, website, **overrides):
    defaults = dict(
        workspace=workspace,
        website=website,
        status=Scan.Status.COMPLETED,
        max_pages=25,
        max_depth=4,
        pages_completed=5,
        overall_score=75,
        category_scores={"seo": {"score": 75, "assessed": True}},
    )
    defaults.update(overrides)
    return Scan.objects.create(**defaults)


def make_issue(workspace, website, **overrides):
    defaults = dict(
        workspace=workspace,
        website=website,
        rule_key="missing_title",
        fingerprint=f"fp-{Issue.objects.count()}",
        title="Missing title",
        category="seo",
        current_severity="high",
        affected_scope="https://example.com/",
        recommendation="Add a title tag.",
        priority_class=Issue.PriorityClass.QUICK_WIN,
        status=Issue.Status.OPEN,
    )
    defaults.update(overrides)
    return Issue.objects.create(**defaults)


class TestProspectAudit:
    def test_includes_health_overview_and_top_opportunities(self, website, workspace):
        scan = make_scan(workspace, website)
        make_issue(workspace, website, priority_class=Issue.PriorityClass.IMMEDIATE_RISK)

        report = generate_prospect_audit(website, scan)

        assert report.report_type == Report.ReportType.PROSPECT_AUDIT
        assert report.content["health_overview"]["overall_score"] == 75
        assert len(report.content["top_opportunities"]) == 1

    def test_competitive_weaknesses_marked_not_assessed(self, website, workspace):
        scan = make_scan(workspace, website)
        report = generate_prospect_audit(website, scan)
        assert report.content["competitive_weaknesses"]["assessed"] is False

    def test_top_opportunities_ordered_immediate_risk_first(self, website, workspace):
        scan = make_scan(workspace, website)
        make_issue(
            workspace, website, title="Growth item",
            priority_class=Issue.PriorityClass.GROWTH_IMPROVEMENT,
            fingerprint="fp-a",
        )
        make_issue(
            workspace, website, title="Critical item",
            priority_class=Issue.PriorityClass.IMMEDIATE_RISK,
            fingerprint="fp-b",
        )

        report = generate_prospect_audit(website, scan)
        titles = [i["title"] for i in report.content["top_opportunities"]]
        assert titles[0] == "Critical item"

    def test_only_open_issues_included(self, website, workspace):
        scan = make_scan(workspace, website)
        make_issue(workspace, website, status=Issue.Status.RESOLVED)

        report = generate_prospect_audit(website, scan)
        assert report.content["top_opportunities"] == []


class TestClientHealthReport:
    def test_trend_summary_reflects_positive_delta(self, website, workspace):
        baseline_scan = make_scan(workspace, website, overall_score=60)
        later_scan = make_scan(workspace, website, overall_score=85)
        baseline = Baseline.objects.create(workspace=workspace, website=website, scan=baseline_scan)
        comparison = Comparison.objects.create(
            workspace=workspace, baseline=baseline, comparison_scan=later_scan,
            overall_score_delta=25,
        )

        report = generate_client_health_report(website, comparison)
        assert "improved by 25" in report.content["trend_summary"]

    def test_new_and_resolved_problems_resolved_from_ids(self, website, workspace):
        baseline_scan = make_scan(workspace, website)
        later_scan = make_scan(workspace, website)
        baseline = Baseline.objects.create(workspace=workspace, website=website, scan=baseline_scan)
        resolved_issue = make_issue(workspace, website, title="Fixed thing")
        comparison = Comparison.objects.create(
            workspace=workspace, baseline=baseline, comparison_scan=later_scan,
            resolved_issue_ids=[str(resolved_issue.id)],
        )

        report = generate_client_health_report(website, comparison)
        assert report.content["resolved_problems"][0]["title"] == "Fixed thing"


class TestRenovationResultsReport:
    def test_before_and_after_scores_included(self, website, workspace):
        baseline_scan = make_scan(workspace, website, overall_score=50)
        later_scan = make_scan(workspace, website, overall_score=90)
        baseline = Baseline.objects.create(workspace=workspace, website=website, scan=baseline_scan)
        comparison = Comparison.objects.create(
            workspace=workspace, baseline=baseline, comparison_scan=later_scan,
            overall_score_delta=40,
        )

        report = generate_renovation_results_report(website, comparison)
        assert report.content["before_and_after_scores"]["before"] == 50
        assert report.content["before_and_after_scores"]["after"] == 90
        assert report.content["before_and_after_scores"]["delta"] == 40

    def test_evidence_honestly_flags_deferred_screenshot_capture(self, website, workspace):
        baseline_scan = make_scan(workspace, website)
        later_scan = make_scan(workspace, website)
        baseline = Baseline.objects.create(workspace=workspace, website=website, scan=baseline_scan)
        comparison = Comparison.objects.create(
            workspace=workspace, baseline=baseline, comparison_scan=later_scan,
        )

        report = generate_renovation_results_report(website, comparison)
        assert "not yet built" in report.content["evidence"]["note"]


class TestShareLink:
    def test_new_link_is_valid(self, website, workspace):
        scan = make_scan(workspace, website)
        report = generate_prospect_audit(website, scan)
        link = create_share_link(report)
        assert link.is_valid() is True

    def test_revoked_link_is_invalid(self, website, workspace):
        scan = make_scan(workspace, website)
        report = generate_prospect_audit(website, scan)
        link = create_share_link(report)
        link.revoked = True
        link.save()
        assert link.is_valid() is False

    def test_expired_link_is_invalid(self, website, workspace):
        from django.utils import timezone
        import datetime

        scan = make_scan(workspace, website)
        report = generate_prospect_audit(website, scan)
        link = create_share_link(report, expires_at=timezone.now() - datetime.timedelta(days=1))
        assert link.is_valid() is False


class TestProposalDraft:
    def test_generates_proposal_from_roadmap_and_issues(self, website, workspace):
        make_issue(workspace, website, title="No H1")
        roadmap = create_roadmap(website, "Renovation Plan")
        add_manual_item(
            roadmap, RoadmapItem.Phase.CRITICAL_REPAIRS, "Fix H1 structure",
            recommendation="Add proper H1 tags sitewide.",
        )

        proposal = generate_proposal_draft(website, roadmap=roadmap)

        assert "No H1" in proposal.problem_statement
        assert "Fix H1 structure" in proposal.scope_of_work
        assert proposal.roadmap == roadmap

    def test_generates_gracefully_with_no_roadmap_or_issues(self, website, workspace):
        proposal = generate_proposal_draft(website)
        assert proposal.title
        assert "No open priority issues" in proposal.problem_statement
