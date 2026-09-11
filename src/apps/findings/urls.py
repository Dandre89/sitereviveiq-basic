from django.urls import path

from . import views

app_name = "findings"

urlpatterns = [
    path("", views.issue_inbox, name="inbox"),
    path("<uuid:pk>/", views.issue_detail, name="detail"),
    path("<uuid:pk>/status/", views.issue_update_status, name="update_status"),
]
