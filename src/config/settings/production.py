import os

from .base import *  # noqa: F401,F403

DEBUG = False

if not SECRET_KEY:  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production")

if not ALLOWED_HOSTS:  # noqa: F405
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must be set in production")

# --- Security requirements, section 12.2 ---
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^accounts/internal/"]  # internal container-to-container calls have no X-Forwarded-Proto
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"

# Login rate limiting is enforced at the view layer (apps.accounts) — see
# LoginRateLimitError there. Django's built-in AxesBackend is not wired in
# Build 1; add django-axes or equivalent before public signup exists.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "scanner": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
