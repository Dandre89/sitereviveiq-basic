from django.contrib import admin

from .models import AuditLogEntry, Workspace, WorkspaceInvite, WorkspaceMembership


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active", "created_at"]
    search_fields = ["name", "slug"]


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "workspace", "role", "created_at"]
    list_filter = ["role"]


@admin.register(WorkspaceInvite)
class WorkspaceInviteAdmin(admin.ModelAdmin):
    list_display = ["email", "workspace", "role", "invited_by", "created_at", "expires_at", "accepted_at", "revoked"]
    list_filter = ["role", "revoked"]
    search_fields = ["email"]


@admin.register(AuditLogEntry)
class AuditLogEntryAdmin(admin.ModelAdmin):
    list_display = ["workspace", "actor", "action", "description", "created_at"]
    list_filter = ["action"]
    search_fields = ["description"]
