from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    # Public, unauthenticated share links — must come before the <uuid:pk>/
    # patterns below so "share" is never swallowed as a pk lookup.
    path("share/r/<uuid:token>/", views.report_public_view, name="public_report"),
    path("share/r/<uuid:token>/pdf/", views.report_public_pdf, name="public_report_pdf"),

    path("", views.report_overview, name="overview"),
    path("website/<uuid:website_pk>/", views.report_list, name="list"),
    path("website/<uuid:website_pk>/generate/", views.generate_report, name="generate"),
    path("<uuid:pk>/", views.report_detail, name="detail"),
    path("<uuid:pk>/preview/", views.report_client_view, name="client_view"),
    path("<uuid:pk>/share/revoke/", views.report_revoke_share_link, name="revoke_share_link"),
    path("<uuid:pk>/export/pdf/", views.report_export_pdf, name="export_pdf"),
    path("<uuid:pk>/delete/", views.report_delete, name="delete"),
]
