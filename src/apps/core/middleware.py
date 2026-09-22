from django.shortcuts import render
from django_ratelimit.exceptions import Ratelimited


class RatelimitMiddleware:
    """
    Turns a tripped @ratelimit decorator (login, password reset, signup —
    see apps.accounts.urls) into a plain 429 page instead of Django's
    generic 403.

    django-ratelimit's own docs describe pointing a `RATELIMIT_VIEW`
    setting at a custom view, but that isn't an actual Django/ratelimit
    mechanism — the decorator just raises django_ratelimit.exceptions.
    Ratelimited (a PermissionDenied subclass), and it's on the app to
    catch it. Doing that narrowly here, via process_exception, means only
    a real rate-limit trip gets the 429 treatment — any other
    PermissionDenied in the app still gets Django's normal 403 handling.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, Ratelimited):
            return render(request, "429.html", status=429)
        return None
