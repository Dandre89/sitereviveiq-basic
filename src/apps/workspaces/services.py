"""
Helpers for workspace admin actions: sending/accepting invites and
recording audit log entries. Kept out of views.py so the "what happens"
logic isn't tangled up with request handling.
"""
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import AuditLogEntry, WorkspaceInvite

INVITE_EXPIRY_DAYS = 14


def log_activity(workspace, actor, action, description) -> None:
    AuditLogEntry.objects.create(
        workspace=workspace, actor=actor, action=action, description=description
    )


def create_invite(workspace, email, role, invited_by) -> WorkspaceInvite:
    return WorkspaceInvite.objects.create(
        workspace=workspace,
        email=email,
        role=role,
        invited_by=invited_by,
        expires_at=timezone.now() + timedelta(days=INVITE_EXPIRY_DAYS),
    )


def send_invite_email(invite: WorkspaceInvite, accept_url: str) -> None:
    """
    Uses whatever EMAIL_BACKEND is configured (console locally, real SMTP
    once deployed) — same pattern as apps.monitoring.notifications.
    """
    try:
        send_mail(
            subject=f"You've been invited to {invite.workspace.name} on SiteRevive IQ",
            message=(
                f"You've been invited to join {invite.workspace.name} on SiteRevive IQ "
                f"as {invite.get_role_display()}.\n\n"
                f"Accept the invite here:\n{accept_url}\n\n"
                f"This link expires in {INVITE_EXPIRY_DAYS} days."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invite.email],
            fail_silently=True,
        )
    except Exception:  # noqa: BLE001 — an email failure must never break the invite flow
        pass
