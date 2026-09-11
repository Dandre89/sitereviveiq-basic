import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def static_v(path):
    """
    Same as {% static %}, but appends `?v=<mtime>` from the file's actual
    last-modified time on disk. Exists because theme.css/tour.js get
    edited frequently during active development and browsers cache
    /static/... URLs aggressively when Django's dev storage serves them
    with no hash in the filename (unlike the hashed ManifestStaticFiles
    URLs production's collectstatic produces) — a plain {% static %} tag
    can silently keep serving a stale cached copy after a real change
    ships. Falls back to a plain {% static %} URL (no query string) if
    the file can't be located on disk for any reason.
    """
    url = static(path)
    found = finders.find(path)
    if not found:
        return url
    try:
        version = int(os.path.getmtime(found))
    except OSError:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}v={version}"
