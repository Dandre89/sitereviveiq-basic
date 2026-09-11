"""
Notification triggers per spec 8.8. Called from apps.scans.services
after a scan completes — see the hook there. Email delivery uses
whatever EMAIL_BACKEND is configured (console locally, real SMTP once
deployed) — this module doesn't know or care which.
"""
from django.conf import settings
from django.core.mail import send_mail

from .models import Notification

CRITICAL_FINDING_SEVERITIES = {"critical"}


def _send_email(notification: Notification) -> None:
    if not notification.recipient or not notification.recipient.email:
        return
    try:
        send_mail(
            subject=f"SiteRevive IQ: {notification.title}",
            message=notification.message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification.recipient.email],
            fail_silently=True,
        )
        notification.email_sent = True
        notification.save(update_fields=["email_sent"])
    except Exception:  # noqa: BLE001 — a notification failure must never break the scan pipeline
        pass


def _create(website, notification_type, title, message, recipient=None, scan=None):
    notification = Notification.objects.create(
        workspace=website.workspace,
        website=website,
        notification_type=notification_type,
        title=title,
        message=message,
        recipient=recipient,
        scan=scan,
    )
    _send_email(notification)
    return notification


def notify_scan_completed(scan, recipient=None) -> Notification | None:
    if not scan.website.workspace.notify_scan_completed:
        return None
    return _create(
        scan.website,
        Notification.NotificationType.SCAN_COMPLETED,
        f"Scan completed for {scan.website.name}",
        f"Scan finished with status {scan.get_status_display()}. "
        f"{scan.pages_completed} pages completed, {scan.pages_failed} failed.",
        recipient=recipient,
        scan=scan,
    )


def notify_critical_findings(scan, recipient=None) -> list[Notification]:
    """One notification per newly-created critical-severity finding in this scan."""
    from apps.findings.models import FindingOccurrence

    if not scan.website.workspace.notify_critical_findings:
        return []

    critical_occurrences = FindingOccurrence.objects.filter(
        scan=scan, severity="critical"
    ).select_related("issue")

    notifications = []
    for occurrence in critical_occurrences:
        notifications.append(
            _create(
                scan.website,
                Notification.NotificationType.CRITICAL_FINDING,
                f"Critical issue found: {occurrence.issue.title}",
                f"{occurrence.issue.title} at {occurrence.issue.affected_scope}. "
                f"{occurrence.issue.recommendation}",
                recipient=recipient,
                scan=scan,
            )
        )
    return notifications


def notify_from_previous_scan(scan, recipient=None) -> list[Notification]:
    """
    Checks this scan for score drops, new opportunities, and returning
    issues by comparing it directly to the website's previous completed
    scan — per spec 8.8, gated by this workspace's own preferences and
    threshold. This build has no Baselines feature (that's Pro+, a
    manually-pinned reference scan); Basic instead always compares
    against whichever scan ran immediately before this one, so these
    three notification types still work with only monthly/on-demand
    scanning and no pinned baseline required.
    """
    from apps.findings.models import FindingOccurrence, Issue
    from apps.scans.models import Scan
    from analyzer.comparison import IssueSnapshot, compare

    website = scan.website
    workspace = website.workspace

    previous_scan = (
        website.scans.filter(status__in=[Scan.Status.COMPLETED, Scan.Status.COMPLETED_WITH_ERRORS])
        .exclude(id=scan.id)
        .order_by("-created_at")
        .first()
    )
    if previous_scan is None:
        return []  # first scan ever — nothing to compare against yet

    def _snapshots(for_scan):
        occurrences = (
            FindingOccurrence.objects.filter(scan=for_scan)
            .select_related("issue")
            .order_by("issue_id")
            .distinct("issue_id")
        )
        return [
            IssueSnapshot(
                issue_id=str(occ.issue_id),
                severity=occ.severity,
                is_first_appearance=(occ.issue.first_seen_scan_id == for_scan.id),
            )
            for occ in occurrences
        ]

    result = compare(_snapshots(previous_scan), _snapshots(scan))

    overall_score_delta = None
    if previous_scan.overall_score is not None and scan.overall_score is not None:
        overall_score_delta = scan.overall_score - previous_scan.overall_score

    notifications = []

    if workspace.notify_score_drops:
        threshold = workspace.score_drop_threshold
        if overall_score_delta is not None and overall_score_delta <= -threshold:
            notifications.append(
                _create(
                    website,
                    Notification.NotificationType.SCORE_DROP,
                    f"Score dropped {abs(overall_score_delta)} points on {website.name}",
                    "Overall score dropped significantly since the last scan — worth reviewing.",
                    recipient=recipient,
                    scan=scan,
                )
            )

    if workspace.notify_new_opportunities and result.new_issue_ids:
        new_issues = Issue.objects.filter(id__in=result.new_issue_ids)
        notifications.append(
            _create(
                website,
                Notification.NotificationType.NEW_OPPORTUNITY,
                f"{len(result.new_issue_ids)} new issue(s) found on {website.name}",
                "New issues: " + "; ".join(i.title for i in new_issues[:5]),
                recipient=recipient,
                scan=scan,
            )
        )

    if workspace.notify_returning_issues and result.returned_issue_ids:
        returned_issues = Issue.objects.filter(id__in=result.returned_issue_ids)
        notifications.append(
            _create(
                website,
                Notification.NotificationType.RETURNING_ISSUE,
                f"{len(result.returned_issue_ids)} issue(s) returned on {website.name}",
                "Previously resolved, now back: " + "; ".join(i.title for i in returned_issues[:5]),
                recipient=recipient,
                scan=scan,
            )
        )

    return notifications


def notify_proposal_response(proposal, recipient=None) -> Notification | None:
    """
    Fired when a client responds to a proposal from the public share
    link (apps.reports.services.record_client_response). Not gated by
    a workspace preference like the scan-driven triggers above — a
    client responding to a proposal is a rare, high-value event an
    agency always wants to hear about, not routine scan noise.
    """
    response_label = proposal.get_client_response_display()
    return _create(
        proposal.website,
        Notification.NotificationType.PROPOSAL_RESPONSE,
        f"{proposal.website.name}: client responded “{response_label}” to a proposal",
        f"{proposal.title} — the client marked this proposal as “{response_label}” "
        f"from the shared link.",
        recipient=recipient,
    )
