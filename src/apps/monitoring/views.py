from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.websites.models import Website
from apps.workspaces.access import require_website_access, scope_websites

from .models import BASIC_NOTIFICATION_TYPES, Notification


@login_required
def notification_list(request):
    notifications = Notification.objects.filter(workspace=request.workspace).select_related(
        "website", "scan"
    )
    if request.accessible_website_ids is not None:
        # Notification.website is nullable (workspace-level notifications
        # aren't tied to one site) — those always stay visible; only
        # site-specific notifications get filtered to the accessible set.
        notifications = notifications.filter(
            Q(website_id__isnull=True) | Q(website_id__in=request.accessible_website_ids)
        )

    website_id = request.GET.get("website", "")
    notification_type = request.GET.get("type", "")
    read_status = request.GET.get("read", "")
    sort = request.GET.get("sort", "newest")

    if website_id:
        notifications = notifications.filter(website_id=website_id)
    if notification_type:
        notifications = notifications.filter(notification_type=notification_type)
    if read_status == "unread":
        notifications = notifications.filter(is_read=False)
    elif read_status == "read":
        notifications = notifications.filter(is_read=True)

    notifications = notifications.order_by("created_at" if sort == "oldest" else "-created_at")[:200]

    return render(
        request,
        "monitoring/list.html",
        {
            "notifications": notifications,
            "websites": scope_websites(
                request, Website.objects.filter(workspace=request.workspace), lookup="pk"
            ).order_by("name"),
            "notification_types": BASIC_NOTIFICATION_TYPES,
            "selected_website": website_id,
            "selected_type": notification_type,
            "selected_read": read_status,
            "selected_sort": sort,
        },
    )


@login_required
def mark_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, workspace=request.workspace)
    if notification.website_id is not None:
        require_website_access(request, notification.website_id)
    if request.method == "POST":
        notification.is_read = True
        notification.save(update_fields=["is_read"])
    return redirect("monitoring:list")


@login_required
def mark_all_read(request):
    if request.method == "POST":
        qs = Notification.objects.filter(workspace=request.workspace, is_read=False)
        if request.accessible_website_ids is not None:
            qs = qs.filter(Q(website_id__isnull=True) | Q(website_id__in=request.accessible_website_ids))
        qs.update(is_read=True)
    return redirect("monitoring:list")
