import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.workspaces.models import WorkspaceScopedModel


class Report(WorkspaceScopedModel):
    """
    Generated report content per spec 8.6. `content` holds the
    structured sections for whichever report_type this is — see
    apps.reports.services for exactly what each type populates. Kept as
    one JSONField rather than per-type models so the eventual "branded
    web report" renderer has one consistent shape to read from
    regardless of type.
    """

    class ReportType(models.TextChoices):
        PROSPECT_AUDIT = "prospect_audit", "Prospect Audit"
        CLIENT_HEALTH = "client_health", "Client Health Report"
        RENOVATION_RESULTS = "renovation_results", "Renovation Results Report"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    website = models.ForeignKey("websites.Website", on_delete=models.CASCADE, related_name="reports")
    report_type = models.CharField(max_length=30, choices=ReportType.choices)
    title = models.CharField(max_length=255)

    # Source data. This build only ever generates Prospect Audit reports,
    # which are scan-only — no comparison/roadmap FKs needed (those power
    # Client Health / Renovation Results / the Proposal generator, all
    # Pro+ features not present here).
    scan = models.ForeignKey(
        "scans.Scan", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    content = models.JSONField(default=dict, blank=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self):
        return f"{self.get_report_type_display()} — {self.website} ({self.generated_at:%Y-%m-%d})"


class ReportShareLink(models.Model):
    """
    A private, unguessable link per spec 8.6 ("branded web report, PDF
    export, private share link"). No password/account required to view
    — the token itself is the access control, same model as most
    agency report-sharing tools. The actual public-facing view is part
    of the deferred UI work; this is the access-control mechanism it
    will sit behind.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="share_links")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)

    def is_valid(self) -> bool:
        if self.revoked:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True

    def __str__(self):
        return f"Share link for {self.report}"

