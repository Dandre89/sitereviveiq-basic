import uuid

from django.conf import settings
from django.db import models

from apps.workspaces.models import WorkspaceScopedModel


class Scan(WorkspaceScopedModel):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        VALIDATING = "validating", "Validating"
        CRAWLING = "crawling", "Crawling"
        ANALYZING = "analyzing", "Analyzing"
        COMPLETED = "completed", "Completed"
        COMPLETED_WITH_ERRORS = "completed_with_errors", "Completed with errors"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    TERMINAL_STATUSES = {
        Status.COMPLETED, Status.COMPLETED_WITH_ERRORS, Status.FAILED, Status.CANCELLED,
    }
    ACTIVE_STATUSES = {Status.QUEUED, Status.VALIDATING, Status.CRAWLING, Status.ANALYZING}

    class Trigger(models.TextChoices):
        MANUAL = "manual", "Manual"
        SCHEDULED = "scheduled", "Scheduled"
        API = "api", "API"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    website = models.ForeignKey("websites.Website", on_delete=models.CASCADE, related_name="scans")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.QUEUED)
    trigger = models.CharField(max_length=20, choices=Trigger.choices, default=Trigger.MANUAL)
    root_url = models.URLField(max_length=2048, blank=True)
    max_pages = models.PositiveIntegerField()
    max_depth = models.PositiveIntegerField()
    pages_discovered = models.PositiveIntegerField(default=0)
    pages_attempted = models.PositiveIntegerField(default=0)
    pages_completed = models.PositiveIntegerField(default=0)
    pages_failed = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    celery_task_id = models.CharField(max_length=255, blank=True)
    crawler_version = models.CharField(max_length=20, default="0.1")
    analyzer_version = models.CharField(max_length=20, blank=True)
    failure_code = models.CharField(max_length=100, blank=True)
    failure_message = models.TextField(blank=True)
    summary_data = models.JSONField(default=dict, blank=True)
    overall_score = models.PositiveSmallIntegerField(null=True, blank=True)
    category_scores = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Scan {self.id} ({self.status}) — {self.website}"

    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES


class ScanPage(models.Model):
    class FetchStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        FETCHING = "fetching", "Fetching"
        COMPLETED = "completed", "Completed"
        SKIPPED = "skipped", "Skipped"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="+")
    scan = models.ForeignKey(Scan, on_delete=models.CASCADE, related_name="pages")
    website = models.ForeignKey("websites.Website", on_delete=models.CASCADE, related_name="+")
    requested_url = models.URLField(max_length=2048)
    normalized_url = models.CharField(max_length=2048)
    final_url = models.URLField(max_length=2048, blank=True)
    parent_url = models.URLField(max_length=2048, blank=True)
    crawl_depth = models.PositiveIntegerField(default=0)
    fetch_status = models.CharField(
        max_length=20, choices=FetchStatus.choices, default=FetchStatus.PENDING
    )
    http_status_code = models.PositiveIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=255, blank=True)
    response_time_ms = models.PositiveIntegerField(null=True, blank=True)
    response_size_bytes = models.PositiveIntegerField(null=True, blank=True)
    redirect_count = models.PositiveIntegerField(default=0)
    redirect_chain = models.JSONField(default=list, blank=True)
    page_title = models.CharField(max_length=1024, blank=True)
    meta_description = models.TextField(blank=True)
    canonical_url = models.URLField(max_length=2048, blank=True)
    robots_directives = models.CharField(max_length=255, blank=True)
    h1_count = models.PositiveIntegerField(default=0)
    h2_count = models.PositiveIntegerField(default=0)
    word_count = models.PositiveIntegerField(default=0)
    internal_link_count = models.PositiveIntegerField(default=0)
    external_link_count = models.PositiveIntegerField(default=0)
    image_count = models.PositiveIntegerField(default=0)
    images_without_alt_count = models.PositiveIntegerField(default=0)
    has_viewport = models.BooleanField(default=False)
    has_mixed_content = models.BooleanField(default=False)
    is_indexable = models.BooleanField(default=True)
    has_phone_link = models.BooleanField(default=False)
    has_contact_form = models.BooleanField(default=False)
    has_cta_link = models.BooleanField(default=False)
    html_hash = models.CharField(max_length=64, blank=True)
    text_hash = models.CharField(max_length=64, blank=True)
    extracted_data = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    error_message = models.TextField(blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scan", "normalized_url"], name="unique_scan_normalized_url"
            )
        ]
        indexes = [models.Index(fields=["scan", "fetch_status"])]

    def __str__(self):
        return f"{self.normalized_url} [{self.fetch_status}]"


class PageLink(models.Model):
    class LinkType(models.TextChoices):
        INTERNAL = "internal", "Internal"
        EXTERNAL = "external", "External"
        MAILTO = "mailto", "Mailto"
        TELEPHONE = "telephone", "Telephone"
        FRAGMENT = "fragment", "Fragment"
        ASSET = "asset", "Asset"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scan = models.ForeignKey(Scan, on_delete=models.CASCADE, related_name="links")
    source_page = models.ForeignKey(ScanPage, on_delete=models.CASCADE, related_name="outbound_links")
    destination_url = models.TextField()
    normalized_destination_url = models.CharField(max_length=2048, blank=True)
    destination_page = models.ForeignKey(
        ScanPage, on_delete=models.SET_NULL, null=True, blank=True, related_name="inbound_links"
    )
    link_type = models.CharField(max_length=20, choices=LinkType.choices)
    anchor_text = models.CharField(max_length=1024, blank=True)
    rel_value = models.CharField(max_length=255, blank=True)
    is_nofollow = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.source_page_id} -> {self.destination_url}"


class ScanEvent(models.Model):
    class Level(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scan = models.ForeignKey(Scan, on_delete=models.CASCADE, related_name="events")
    level = models.CharField(max_length=20, choices=Level.choices, default=Level.INFO)
    event_type = models.CharField(max_length=100)
    message = models.TextField()
    event_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.level}] {self.event_type}: {self.message[:60]}"
