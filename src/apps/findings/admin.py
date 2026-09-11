from django.contrib import admin

from .models import FindingOccurrence, Issue


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = [
        "title", "website", "rule_key", "current_severity", "priority_class", "status", "last_seen_at",
    ]
    list_filter = ["website", "priority_class", "current_severity", "status", "category", "rule_key"]
    search_fields = ["title", "affected_scope", "rule_key"]


@admin.register(FindingOccurrence)
class FindingOccurrenceAdmin(admin.ModelAdmin):
    list_display = ["issue", "scan", "page", "severity", "created_at"]
    list_filter = ["severity"]
