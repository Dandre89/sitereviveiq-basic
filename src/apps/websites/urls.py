from django.urls import path

from . import views

app_name = "websites"

urlpatterns = [
    path("", views.website_list, name="list"),
    path("add/", views.website_add, name="add"),
    path("<uuid:pk>/", views.website_detail, name="detail"),
    path("<uuid:pk>/edit/", views.website_edit, name="edit"),
    path("<uuid:pk>/archive/", views.website_archive, name="archive"),
    path("<uuid:pk>/unarchive/", views.website_unarchive, name="unarchive"),
    path("<uuid:pk>/scan/", views.website_run_scan, name="run_scan"),
]
