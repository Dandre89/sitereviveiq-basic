from django.urls import path

from . import views

app_name = "workspaces"

urlpatterns = [
    path("", views.team_list, name="list"),
    path("settings/general/", views.workspace_update_general, name="update_general"),
    path("settings/notifications/", views.workspace_update_notifications, name="update_notifications"),
]
