from django.conf import settings


def app_meta(request):
    """
    App-wide metadata every template can reach without each view having to
    pass it explicitly — currently just the release version shown under
    the logo in the sidebar (base.html).
    """
    return {"app_version": settings.APP_VERSION}
