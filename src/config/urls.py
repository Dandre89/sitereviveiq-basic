from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("websites/", include("apps.websites.urls")),
    path("issues/", include("apps.findings.urls")),
    path("scans/", include("apps.scans.urls")),
    path("reports/", include("apps.reports.urls")),
    path("notifications/", include("apps.monitoring.urls")),
    path("billing/", include("apps.billing.urls")),
    path("team/", include("apps.workspaces.urls")),
    path("", include("apps.core.urls")),
]

if settings.DEBUG:
    # Development-only media serving for uploaded workspace logos. A real
    # deployment needs a proper file store (S3, etc.) in front of MEDIA_ROOT
    # instead — this is not it.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
