from django.contrib import admin

from .models import PageLink, Scan, ScanEvent, ScanPage


@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    list_display = [
        "id", "website", "status", "trigger", "overall_score",
        "pages_completed", "pages_failed", "created_at",
    ]
    list_filter = ["status", "trigger"]


@admin.register(ScanPage)
class ScanPageAdmin(admin.ModelAdmin):
    list_display = ["normalized_url", "scan", "fetch_status", "http_status_code", "crawl_depth"]
    list_filter = ["fetch_status"]
    search_fields = ["normalized_url"]


admin.site.register(PageLink)
admin.site.register(ScanEvent)
