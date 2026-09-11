import uuid

from django.conf import settings
from django.db import models

from apps.workspaces.models import WorkspaceScopedModel


class Website(WorkspaceScopedModel):
    class WebsiteType(models.TextChoices):
        PROSPECT = "prospect", "Prospect"
        CLIENT = "client", "Client"
        INTERNAL = "internal", "Internal"
        COMPETITOR = "competitor", "Competitor"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        ARCHIVED = "archived", "Archived"

    class MonitoringFrequency(models.TextChoices):
        # No WEEKLY here — this tier caps scheduled scanning at Monthly
        # (Pro adds Weekly on top). Deliberately a real choice restriction,
        # not a UI-only hide: a website row simply can't be set to weekly
        # monitoring in this build.
        NONE = "none", "Not monitored"
        MONTHLY = "monthly", "Monthly"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    submitted_url = models.URLField(max_length=2048)
    canonical_url = models.URLField(max_length=2048, blank=True)
    normalized_host = models.CharField(max_length=255)
    website_type = models.CharField(
        max_length=20, choices=WebsiteType.choices, default=WebsiteType.PROSPECT
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    monitoring_frequency = models.CharField(
        max_length=10, choices=MonitoringFrequency.choices, default=MonitoringFrequency.NONE
    )
    tracks_competitor_for = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="competitors",
        help_text="Set only for competitor entries — the prospect/client website this competes with.",
    )
    max_pages = models.PositiveIntegerField(default=25)
    max_depth = models.PositiveIntegerField(default=4)
    last_scan = models.ForeignKey(
        "scans.Scan", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "normalized_host"], name="unique_workspace_host"
            ),
            models.CheckConstraint(
                check=models.Q(max_pages__gte=1) & models.Q(max_pages__lte=500),
                name="max_pages_bounded",
            ),
            models.CheckConstraint(
                check=models.Q(max_depth__gte=1) & models.Q(max_depth__lte=10),
                name="max_depth_bounded",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.normalized_host})"

    def has_active_scan(self) -> bool:
        return self.scans.filter(
            status__in=[
                "queued", "validating", "crawling", "analyzing",
            ]
        ).exists()
