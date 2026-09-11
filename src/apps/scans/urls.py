from django.urls import path

from . import views

app_name = "scans"

urlpatterns = [
    path("<uuid:pk>/", views.scan_progress, name="progress"),
]
