from django.contrib import admin

from .models import Website


@admin.register(Website)
class WebsiteAdmin(admin.ModelAdmin):
    list_display = [
        "name", "normalized_host", "website_type", "status",
        "monitoring_frequency", "tracks_competitor_for", "workspace",
    ]
    list_filter = ["website_type", "status", "monitoring_frequency"]
    search_fields = ["name", "normalized_host"]
