import datetime

import pytest
from django.core import mail
from django.utils import timezone

from apps.comparisons.models import Baseline, Comparison
from apps.findings.models import FindingOccurrence, Issue
from apps.monitoring.competitors import (
    MAX_COMPETITORS,
    TooManyCompetitorsError,
    add_competitor,
    compare_to_competitors,
)
from apps.monitoring.models import Notification
from apps.monitoring.notifications import (
    notify_critical_findings,
    notify_from_comparison,
    notify_scan_completed,
)
from apps.monitoring.tasks import FREQUENCY_INTERVALS
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
        workspace=workspace, website=website, status=Scan.Status.COMPLETED,
        max_pages=25, max_depth=4, pages_completed=5, pages_failed=0,
        overall_score=80,
    )
    defaults.update(overrides)
    return Scan.objects.create(**defaults)


class TestNotifyScanCompleted:
    def test_creates_notification(self, website, workspace):
        scan = make_scan(workspace, website)
        notification = notify_scan_completed(scan)
        assert notification.notification_type == Notification.NotificationType.SCAN_COMPLETED
        assert notification.website == website

    def test_sends_console_email_when_recipient_has_email(self, website, workspace, django_user_model):
        user = django_user_model.objects.create_user(email="darren@example.com", password="x")
        scan = make_scan(workspace, website)
        notify_scan_completed(scan, recipient=user)
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["darren@example.com"]

    def test_no_email_attempted_without_recipient(self, website, workspace):
        scan = make_scan(workspace, website)
        notify_scan_completed(scan, recipient=None)
        assert len(mail.outbox) == 0


class TestNotifyCriticalFindings:
    def test_one_notification_per_critical_occurrence(self, website, workspace):
        scan = make_scan(workspace, website)
        issue = Issue.objects.create(
            workspace=workspace, website=website, rule_key="x", fingerprint="fp1",
            title="Critical thing", category="technical", current_severity="critical",
            affected_scope="https://example.com/",
        )
        FindingOccurrence.objects.create(issue=issue, scan=scan, severity="critical", evidence={})

        notifications = notify_critical_findings(scan)
        assert len(notifications) == 1
        assert notifications[0].notification_type == Notification.NotificationType.CRITICAL_FINDING

    def test_no_notification_for_non_critical_findings(self, website, workspace):
        scan = make_scan(workspace, website)
        issue = Issue.objects.create(
            workspace=workspace, website=website, rule_key="x", fingerprint="fp1",
            title="Minor thing", category="seo", current_severity="low",
            affected_scope="https://example.com/",
        )
        FindingOccurrence.objects.create(issue=issue, scan=scan, severity="low", evidence={})

        assert notify_critical_findings(scan) == []


class TestNotifyFromComparison:
    def _make_comparison(self, workspace, website, **overrides):
        baseline_scan = make_scan(workspace, website)
        later_scan = make_scan(workspace, website)
        baseline = Baseline.objects.create(workspace=workspace, website=website, scan=baseline_scan)
        defaults = dict(workspace=workspace, baseline=baseline, comparison_scan=later_scan)
        defaults.update(overrides)
        return Comparison.objects.create(**defaults)

    def test_score_drop_triggers_notification(self, website, workspace, settings):
        settings.SCORE_DROP_NOTIFICATION_THRESHOLD = 10
        comparison = self._make_comparison(workspace, website, overall_score_delta=-15)
        notifications = notify_from_comparison(comparison)
        types = [n.notification_type for n in notifications]
        assert Notification.NotificationType.SCORE_DROP in types

    def test_small_score_drop_does_not_trigger(self, website, workspace, settings):
        settings.SCORE_DROP_NOTIFICATION_THRESHOLD = 10
        comparison = self._make_comparison(workspace, website, overall_score_delta=-3)
        notifications = notify_from_comparison(comparison)
        types = [n.notification_type for n in notifications]
        assert Notification.NotificationType.SCORE_DROP not in types

    def test_new_issues_trigger_notification(self, website, workspace):
        issue = Issue.objects.create(
            workspace=workspace, website=website, rule_key="x", fingerprint="fp1",
            title="New thing", category="seo", current_severity="high",
            affected_scope="https://example.com/",
        )
        comparison = self._make_comparison(workspace, website, new_issue_ids=[str(issue.id)])
        notifications = notify_from_comparison(comparison)
        types = [n.notification_type for n in notifications]
        assert Notification.NotificationType.NEW_OPPORTUNITY in types

    def test_returned_issues_trigger_notification(self, website, workspace):
        issue = Issue.objects.create(
            workspace=workspace, website=website, rule_key="x", fingerprint="fp1",
            title="Back again", category="seo", current_severity="high",
            affected_scope="https://example.com/",
        )
        comparison = self._make_comparison(workspace, website, returned_issue_ids=[str(issue.id)])
        notifications = notify_from_comparison(comparison)
        types = [n.notification_type for n in notifications]
        assert Notification.NotificationType.RETURNING_ISSUE in types

    def test_no_change_triggers_nothing(self, website, workspace):
        comparison = self._make_comparison(workspace, website, overall_score_delta=0)
        assert notify_from_comparison(comparison) == []


class TestCompetitors:
    def test_add_competitor_creates_website(self, website, workspace):
        competitor = add_competitor(website, "Rival Co", "https://rival.example.com/")
        assert competitor.website_type == Website.WebsiteType.COMPETITOR
        assert competitor.tracks_competitor_for == website

    def test_enforces_max_competitors(self, website, workspace):
        for i in range(MAX_COMPETITORS):
            add_competitor(website, f"Rival {i}", f"https://rival{i}.example.com/")
        with pytest.raises(TooManyCompetitorsError):
            add_competitor(website, "One too many", "https://rivalx.example.com/")

    def test_compare_to_competitors_ranks_by_score(self, website, workspace):
        competitor = add_competitor(website, "Rival Co", "https://rival.example.com/")
        make_scan(workspace, website, overall_score=60)
        make_scan(workspace, competitor, overall_score=90)

        result = compare_to_competitors(website)

        assert result["rank"] == 2  # primary scored lower than its one competitor
        assert result["total_ranked"] == 2

    def test_unscanned_competitor_shows_null_score_not_dropped(self, website, workspace):
        add_competitor(website, "Rival Co", "https://rival.example.com/")
        make_scan(workspace, website, overall_score=60)

        result = compare_to_competitors(website)
        assert len(result["entries"]) == 2
        unscanned = [e for e in result["entries"] if e["overall_score"] is None]
        assert len(unscanned) == 1


class TestScheduledScanIntervals:
    def test_weekly_interval_is_seven_days(self):
        assert FREQUENCY_INTERVALS["weekly"] == datetime.timedelta(days=7)

    def test_monthly_interval_is_thirty_days(self):
        assert FREQUENCY_INTERVALS["monthly"] == datetime.timedelta(days=30)

    def test_website_with_no_scan_is_always_due(self, website, workspace):
        website.monitoring_frequency = Website.MonitoringFrequency.WEEKLY
        website.save()
        assert website.scans.filter(status__in=Scan.TERMINAL_STATUSES).exists() is False

    def test_recent_scan_is_not_due(self, website, workspace):
        website.monitoring_frequency = Website.MonitoringFrequency.WEEKLY
        website.save()
        make_scan(workspace, website)
        last_scan = website.scans.filter(status__in=Scan.TERMINAL_STATUSES).order_by(
            "-created_at"
        ).first()
        is_due = (timezone.now() - last_scan.created_at) >= FREQUENCY_INTERVALS["weekly"]
        assert is_due is False

    def test_old_scan_is_due(self, website, workspace):
        website.monitoring_frequency = Website.MonitoringFrequency.WEEKLY
        website.save()
        scan = make_scan(workspace, website)
        Scan.objects.filter(pk=scan.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=10)
        )
        last_scan = website.scans.filter(status__in=Scan.TERMINAL_STATUSES).order_by(
            "-created_at"
        ).first()
        is_due = (timezone.now() - last_scan.created_at) >= FREQUENCY_INTERVALS["weekly"]
        assert is_due is True
