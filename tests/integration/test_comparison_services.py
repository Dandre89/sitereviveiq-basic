import pytest

from apps.comparisons.models import Baseline
from apps.comparisons.services import compute_comparison, create_baseline
from apps.findings.models import FindingOccurrence, Issue
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
        overall_score=80,
        category_scores={"seo": {"score": 80, "assessed": True}},
    )
    defaults.update(overrides)
    return Scan.objects.create(**defaults)


def make_issue(workspace, website, first_seen_scan, **overrides):
    defaults = dict(
        workspace=workspace,
        website=website,
        rule_key="missing_title",
        fingerprint=f"fp-{Issue.objects.count()}",
        title="Missing title",
        category="seo",
        current_severity="high",
        affected_scope="https://example.com/",
        first_seen_scan=first_seen_scan,
        last_seen_scan=first_seen_scan,
    )
    defaults.update(overrides)
    return Issue.objects.create(**defaults)


def make_occurrence(issue, scan, severity="high"):
    return FindingOccurrence.objects.create(issue=issue, scan=scan, severity=severity, evidence={})


class TestCreateBaseline:
    def test_creates_active_baseline(self, website, workspace):
        scan = make_scan(workspace, website)
        baseline = create_baseline(website, scan, name="Pre-renovation")
        assert baseline.is_active is True
        assert baseline.scan == scan

    def test_creating_a_new_baseline_deactivates_the_old_one(self, website, workspace):
        scan1 = make_scan(workspace, website)
        scan2 = make_scan(workspace, website)

        first = create_baseline(website, scan1, name="First")
        second = create_baseline(website, scan2, name="Second")

        first.refresh_from_db()
        assert first.is_active is False
        assert second.is_active is True

    def test_only_one_active_baseline_per_website_at_db_level(self, website, workspace):
        scan1 = make_scan(workspace, website)
        scan2 = make_scan(workspace, website)
        create_baseline(website, scan1)
        create_baseline(website, scan2)
        assert Baseline.objects.filter(website=website, is_active=True).count() == 1


class TestComputeComparison:
    def test_resolved_issue_detected(self, website, workspace):
        baseline_scan = make_scan(workspace, website, overall_score=70)
        later_scan = make_scan(workspace, website, overall_score=90)

        issue = make_issue(workspace, website, first_seen_scan=baseline_scan)
        make_occurrence(issue, baseline_scan)
        # Not re-created in later_scan -> resolved.

        baseline = create_baseline(website, baseline_scan)
        comparison = compute_comparison(baseline, later_scan)

        assert str(issue.id) in comparison.resolved_issue_ids
        assert comparison.overall_score_delta == 20

    def test_new_issue_detected(self, website, workspace):
        baseline_scan = make_scan(workspace, website)
        later_scan = make_scan(workspace, website)

        issue = make_issue(workspace, website, first_seen_scan=later_scan)
        make_occurrence(issue, later_scan)

        baseline = create_baseline(website, baseline_scan)
        comparison = compute_comparison(baseline, later_scan)

        assert str(issue.id) in comparison.new_issue_ids

    def test_returned_issue_detected(self, website, workspace):
        original_scan = make_scan(workspace, website)
        baseline_scan = make_scan(workspace, website)
        later_scan = make_scan(workspace, website)

        # Issue first appeared in an earlier scan (before the baseline),
        # was absent at baseline time, and comes back in the later scan.
        issue = make_issue(workspace, website, first_seen_scan=original_scan)
        make_occurrence(issue, original_scan)
        make_occurrence(issue, later_scan)

        baseline = create_baseline(website, baseline_scan)
        comparison = compute_comparison(baseline, later_scan)

        assert str(issue.id) in comparison.returned_issue_ids
        assert str(issue.id) not in comparison.new_issue_ids

    def test_worsened_issue_detected(self, website, workspace):
        baseline_scan = make_scan(workspace, website)
        later_scan = make_scan(workspace, website)

        issue = make_issue(workspace, website, first_seen_scan=baseline_scan)
        make_occurrence(issue, baseline_scan, severity="low")
        make_occurrence(issue, later_scan, severity="critical")

        baseline = create_baseline(website, baseline_scan)
        comparison = compute_comparison(baseline, later_scan)

        assert str(issue.id) in comparison.worsened_issue_ids

    def test_category_score_deltas_computed(self, website, workspace):
        baseline_scan = make_scan(
            workspace, website, category_scores={"seo": {"score": 60, "assessed": True}}
        )
        later_scan = make_scan(
            workspace, website, category_scores={"seo": {"score": 85, "assessed": True}}
        )

        baseline = create_baseline(website, baseline_scan)
        comparison = compute_comparison(baseline, later_scan)

        assert comparison.category_score_deltas["seo"] == 25

    def test_pages_completed_delta_computed(self, website, workspace):
        baseline_scan = make_scan(workspace, website, pages_completed=3)
        later_scan = make_scan(workspace, website, pages_completed=8)

        baseline = create_baseline(website, baseline_scan)
        comparison = compute_comparison(baseline, later_scan)

        assert comparison.pages_completed_delta == 5
