import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)

    # Notification preferences — gates apps.monitoring.notifications, which
    # already does the real work (creates Notification rows, sends real
    # email via send_mail). These flags decide whether each trigger fires
    # at all for this workspace; nothing here is cosmetic.
    notify_critical_findings = models.BooleanField(default=True)
    notify_score_drops = models.BooleanField(default=True)
    notify_scan_completed = models.BooleanField(default=True)
    notify_new_opportunities = models.BooleanField(default=True)
    notify_returning_issues = models.BooleanField(default=True)
    score_drop_threshold = models.PositiveIntegerField(default=10)

    # Report branding — read by the real public share-link pages
    # (reports/public_report.html, reports/public_proposal.html).
    logo = models.ImageField(upload_to="workspace_logos/", blank=True, null=True)
    show_powered_by = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class WorkspaceMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MEMBER = "member", "Member"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspace_memberships"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "user"], name="unique_workspace_user")
        ]

    def __str__(self):
        return f"{self.user} @ {self.workspace} ({self.role})"


class WorkspaceInvite(models.Model):
    """
    A pending invitation to join a workspace. No User row is created
    until the invite is accepted — avoids orphan accounts for invites
    that are never opened. Same unguessable-token access-control
    pattern as ReportShareLink/ProposalShareLink in apps.reports.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="invites")
    email = models.EmailField()
    role = models.CharField(
        max_length=20, choices=WorkspaceMembership.Role.choices, default=WorkspaceMembership.Role.MEMBER
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def is_valid(self) -> bool:
        if self.revoked or self.accepted_at:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            return False
        return True

    def __str__(self):
        return f"Invite for {self.email} to {self.workspace}"


class AuditLogEntry(models.Model):
    """
    Lightweight admin activity trail: who invited/removed/changed a
    role, or edited workspace settings, and when. This is specifically
    the "who did what" history for workspace administration — not the
    product's own website-audit features (see apps.findings/apps.scans
    for that "audit" meaning).
    """

    class Action(models.TextChoices):
        INVITE_SENT = "invite_sent", "Invite sent"
        INVITE_REVOKED = "invite_revoked", "Invite revoked"
        INVITE_RESENT = "invite_resent", "Invite resent"
        MEMBER_JOINED = "member_joined", "Member joined"
        ROLE_CHANGED = "role_changed", "Role changed"
        MEMBER_REMOVED = "member_removed", "Member removed"
        WORKSPACE_UPDATED = "workspace_updated", "Workspace settings updated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="audit_log_entries")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    action = models.CharField(max_length=30, choices=Action.choices)
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_action_display()} — {self.description}"


class WorkspaceScopedModel(models.Model):
    """
    Abstract base for every business-owned model. Section 12.3 requires
    every website, scan, page, issue, report, roadmap, and comparison to
    resolve to an owning workspace, and query services to require
    workspace context — this base makes that the default, not opt-in.
    """

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="+")

    class Meta:
        abstract = True
