import uuid

from django.db import models

from apps.workspaces.models import WorkspaceScopedModel


class Issue(WorkspaceScopedModel):
    """
    A persistent website problem tracked ACROSS scans — this is the row
    that carries first_seen/last_seen/status. Individual scan evidence
    lives in FindingOccurrence. Deduped via `fingerprint`, which is a
    stable hash of (website, rule_key, affected_scope) so the same
    problem re-detected on rescan updates this row instead of creating a
    duplicate.
    """

    class Category(models.TextChoices):
        TECHNICAL = "technical", "Technical"
        SEO = "seo", "SEO"
        CONTENT = "content", "Content"
        CONVERSION = "conversion", "Conversion"
        ACCESSIBILITY = "accessibility", "Accessibility"
        SECURITY_TRUST = "security_trust", "Security/Trust"
        COMPETITIVE = "competitive", "Competitive"

    class Severity(models.TextChoices):
        CRITICAL = "critical", "Critical"
        HIGH = "high", "High"
        MEDIUM = "medium", "Medium"
        LOW = "low", "Low"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACCEPTED = "accepted", "Accepted"
        PLANNED = "planned", "Planned"
        IN_PROGRESS = "in_progress", "In Progress"
        RESOLVED = "resolved", "Resolved"
        IGNORED = "ignored", "Ignored"

    class PriorityClass(models.TextChoices):
        IMMEDIATE_RISK = "immediate_risk", "Immediate Risk"
        QUICK_WIN = "quick_win", "Quick Win"
        GROWTH_IMPROVEMENT = "growth_improvement", "Growth Improvement"
        STRATEGIC_RENOVATION = "strategic_renovation", "Strategic Renovation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    website = models.ForeignKey("websites.Website", on_delete=models.CASCADE, related_name="issues")
    rule_key = models.CharField(max_length=100)
    fingerprint = models.CharField(max_length=64)  # sha256 hex
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=Category.choices)
    current_severity = models.CharField(max_length=20, choices=Severity.choices)
    business_impact = models.CharField(max_length=100, blank=True)
    affected_scope = models.CharField(
        max_length=2048,
        help_text="The specific URL, or a site-wide pattern label, this issue applies to.",
    )
    recommendation = models.TextField(blank=True)
    estimated_effort = models.CharField(max_length=20, blank=True)  # Small/Medium/Large
    priority_class = models.CharField(max_length=30, choices=PriorityClass.choices, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    ignored_reason = models.TextField(blank=True)
    first_seen_scan = models.ForeignKey(
        "scans.Scan", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    last_seen_scan = models.ForeignKey(
        "scans.Scan", on_delete=models.SET_NULL, null=True, related_name="+"
    )
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["website", "fingerprint"], name="unique_website_fingerprint"
            )
        ]
        indexes = [models.Index(fields=["website", "status"])]
        ordering = ["-last_seen_at"]

    def __str__(self):
        return f"{self.title} ({self.get_current_severity_display()}) — {self.affected_scope}"


class FindingOccurrence(models.Model):
    """Evidence that an Issue appeared in one specific scan (and page, if page-scoped)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="occurrences")
    scan = models.ForeignKey("scans.Scan", on_delete=models.CASCADE, related_name="findings")
    page = models.ForeignKey(
        "scans.ScanPage", on_delete=models.SET_NULL, null=True, blank=True, related_name="findings"
    )
    severity = models.CharField(max_length=20, choices=Issue.Severity.choices)
    evidence = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["scan"])]

    def __str__(self):
        return f"{self.issue.rule_key} in scan {self.scan_id}"


# This tier only ever detects/shows these four categories — Conversion,
# Accessibility, and Competitive are Pro+ (see apps.findings.services.
# analyze_scan, which filters findings down to this same set before any
# Issue row is created). Category itself still has all seven choices
# (harmless — nothing in this build can ever create an Issue outside
# this set), but any UI category filter/dropdown should use this
# narrowed list instead of the full Issue.Category.choices, so it never
# offers an option that can never match anything.
BASIC_ISSUE_CATEGORIES = [
    (Issue.Category.TECHNICAL, "Technical"),
    (Issue.Category.SEO, "SEO"),
    (Issue.Category.CONTENT, "Content"),
    (Issue.Category.SECURITY_TRUST, "Security/Trust"),
]
