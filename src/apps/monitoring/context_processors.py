def unread_notifications(request):
    if not request.user.is_authenticated or not getattr(request, "workspace", None):
        return {}
    from .models import Notification

    count = Notification.objects.filter(workspace=request.workspace, is_read=False).count()
    return {"unread_notification_count": count}
