import uuid

from django.conf import settings
from django.db import models

from apps.workspaces.models import WorkspaceScopedModel


class Notification(WorkspaceScopedModel):
    """
    Per spec 8.8: "Generate notifications for completed scans, critical
    findings, significant score drops, new opportunities, and returning
    issues." Delivery is via Django's email backend (console backend by
    default locally — see settings) plus this in-app record, which is
    what admin/UI actually reads from; email is a notification of the
    notification, not the source of truth.
    """

    class NotificationType(models.TextChoices):
        SCAN_COMPLETED = "scan_completed", "Scan completed"
        CRITICAL_FINDING = "critical_finding", "Critical finding"
        SCORE_DROP = "score_drop", "Significant score drop"
        NEW_OPPORTUNITY = "new_opportunity", "New opportunity"
        RETURNING_ISSUE = "returning_issue", "Returning issue"
        PROPOSAL_RESPONSE = "proposal_response", "Proposal response"
        # No migration needed — adding a TextChoices value only changes
        # Python-level validation, not the underlying CharField column.
        CREDITS_EXHAUSTED = "credits_exhausted", "Monitoring paused — out of credits"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    website = models.ForeignKey("websites.Website", on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length=30, choices=NotificationType.choices)
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)

    scan = models.ForeignKey("scans.Scan", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # No FK to a Comparison/Baseline row here — this build has no Baselines
    # feature (Pro+ only). Score-drop/new-opportunity/returning-issue
    # notifications compare each scan to the website's previous scan
    # directly instead of a pinned baseline; see apps.monitoring.notifications.

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    is_read = models.BooleanField(default=False)
    email_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["website", "is_read"])]

    def __str__(self):
        return f"[{self.get_notification_type_display()}] {self.title}"


# This tier never generates a proposal_response notification — there's
# no Proposal generator (Pro+ only). NotificationType keeps all six
# values (harmless — nothing in this build can ever create one with
# PROPOSAL_RESPONSE), but the notification-type filter dropdown should
# use this narrowed list instead of the full NotificationType.choices.
BASIC_NOTIFICATION_TYPES = [
    (Notification.NotificationType.SCAN_COMPLETED, "Scan completed"),
    (Notification.NotificationType.CRITICAL_FINDING, "Critical finding"),
    (Notification.NotificationType.SCORE_DROP, "Significant score drop"),
    (Notification.NotificationType.NEW_OPPORTUNITY, "New opportunity"),
    (Notification.NotificationType.RETURNING_ISSUE, "Returning issue"),
    # Unlike PROPOSAL_RESPONSE, this one absolutely can happen here —
    # Basic still has scheduled monitoring (None/Monthly), which is what
    # triggers this notification when a workspace runs out of credits.
    (Notification.NotificationType.CREDITS_EXHAUSTED, "Monitoring paused — out of credits"),
]
