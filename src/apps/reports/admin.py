from django.contrib import admin

from .models import Report, ReportShareLink


class ReportShareLinkInline(admin.TabularInline):
    model = ReportShareLink
    extra = 0
    readonly_fields = ["token", "view_count", "last_viewed_at", "created_at"]
    fields = ["token", "expires_at", "revoked", "view_count", "last_viewed_at", "created_at"]


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["title", "website", "report_type", "generated_at"]
    list_filter = ["report_type", "website"]
    search_fields = ["title"]
    readonly_fields = ["content", "generated_at"]
    inlines = [ReportShareLinkInline]
