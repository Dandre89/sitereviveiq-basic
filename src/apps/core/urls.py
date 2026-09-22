from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("settings/", views.settings_view, name="settings"),
    path("legal/terms/", views.legal_terms, name="legal_terms"),
    path("legal/privacy/", views.legal_privacy, name="legal_privacy"),
    path("legal/refund-policy/", views.legal_refund_policy, name="legal_refund_policy"),
]
