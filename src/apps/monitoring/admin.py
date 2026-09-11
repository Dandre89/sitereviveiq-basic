from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = [
        "title", "website", "notification_type", "recipient", "is_read", "email_sent", "created_at",
    ]
    list_filter = ["notification_type", "is_read", "email_sent", "website"]
    search_fields = ["title", "message"]
