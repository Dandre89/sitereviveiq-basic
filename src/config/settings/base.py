"""
Base settings shared by development and production.
Nothing environment-specific lives here except sane defaults.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")

DEBUG = False

ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h]

CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "apps.core",
    "apps.accounts",
    "apps.workspaces",
    "apps.websites",
    "apps.scans",
    "apps.findings",
    "apps.reports",
    "apps.monitoring",
    "apps.billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.workspaces.middleware.CurrentWorkspaceMiddleware",
    "apps.billing.middleware.SubscriptionEnforcementMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.monitoring.context_processors.unread_notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

AUTH_USER_MODEL = "accounts.User"

# Set only when this app shares a Postgres *instance* with other
# SiteRevive IQ tiers (e.g. the free Render Postgres, shared across
# Enterprise/Pro/Basic). Isolates this app's tables into their own
# schema instead of the default "public" one. See
# apps/core/management/commands/ensure_schema.py, which creates the
# schema on deploy before migrate runs. Leave unset for local dev.
POSTGRES_SCHEMA = os.environ.get("POSTGRES_SCHEMA", "")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "sitereviveiq"),
        "USER": os.environ.get("POSTGRES_USER", "sitereviveiq"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "postgres"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": (
            # Deliberately NOT "{schema},public" -- Postgres resolves
            # references to already-existing tables by walking the whole
            # search_path, not just the first entry. Since this Postgres
            # instance is shared with other SiteRevive IQ tiers that migrated
            # directly into "public" (no schema isolation), including
            # "public" here would make ALTER TABLE statements against
            # same-named tables silently target the wrong tier's tables
            # once this tier's own schema has no matching table yet. Keeping
            # the search_path to just this tier's schema forces every
            # migration to create genuinely fresh, isolated tables.
            {"options": f"-c search_path={POSTGRES_SCHEMA}"}
            if POSTGRES_SCHEMA
            else {}
        ),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "America/New_York")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# User uploads (workspace logos). Served via config.urls in DEBUG mode
# only — a real deployment needs a proper file store (S3, etc.) in
# front of this instead, which is out of scope here.
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

# --- Celery ---
CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_TIME_LIMIT = 600  # 10-minute hard scan limit per the spec
CELERY_WORKER_CONCURRENCY = 1
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# --- Scanner (Appendix B env vars) ---
SCANNER_USER_AGENT = os.environ.get("SCANNER_USER_AGENT", "SiteReviveIQBot/0.1")
SCANNER_MAX_PAGES = int(os.environ.get("SCANNER_MAX_PAGES", 25))
SCANNER_MAX_DEPTH = int(os.environ.get("SCANNER_MAX_DEPTH", 4))
SCANNER_REQUEST_TIMEOUT = float(os.environ.get("SCANNER_REQUEST_TIMEOUT", 15))
SCANNER_MAX_RESPONSE_BYTES = int(os.environ.get("SCANNER_MAX_RESPONSE_BYTES", 5 * 1024 * 1024))
SCANNER_MAX_REDIRECTS = int(os.environ.get("SCANNER_MAX_REDIRECTS", 5))
SCANNER_MAX_SCAN_SECONDS = int(os.environ.get("SCANNER_MAX_SCAN_SECONDS", 600))

SITE_DOMAIN = os.environ.get("SITE_DOMAIN", "localhost")
SITE_PROTOCOL = os.environ.get("SITE_PROTOCOL", "https")

# --- Email (notifications) ---
# Defaults to the console backend so notifications work locally with zero
# setup. Set EMAIL_HOST in the environment to switch to real SMTP delivery
# (e.g. when deploying) — nothing here requires that to exist.
if os.environ.get("EMAIL_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ["EMAIL_HOST"]
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 587))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true").lower() == "true"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "notifications@sitereviveiq.com")

# --- Scoring: score-drop threshold that triggers a notification (Build 7) ---
SCORE_DROP_NOTIFICATION_THRESHOLD = int(os.environ.get("SCORE_DROP_NOTIFICATION_THRESHOLD", 10))

# --- Billing (Stripe) ---
# Blank by default, same shape as the email block above: with no
# STRIPE_SECRET_KEY set, apps.billing.middleware.SubscriptionEnforcementMiddleware
# is a full no-op (nothing gets blocked) so local/dev and any environment
# that hasn't been wired up for real billing yet behave exactly as they
# did before this app existed. Set all three in the environment to turn
# enforcement on for real — see apps/billing/services.py and
# apps/billing/views.py::stripe_webhook for what each one is used for.
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")

# Shared secret checked by apps.accounts.views.internal_trigger_password_reset
# — lets the separate internal admin console trigger this app's own
# password-reset email flow for a given user, server-to-server. Blank
# by default, which makes that endpoint refuse every request (see
# HttpResponseForbidden there) until this is explicitly set.
INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# Self-serve checkout price catalog (test mode, Sept 2026). This build
# only sells Basic (no Pro/Enterprise here), so this is keyed by
# interval only — contrast with the Pro codebase's STRIPE_PRICE_IDS,
# which is keyed by (plan, interval). apps.billing.services.get_price_id
# is the only place that should read this dict.
STRIPE_PRICE_IDS = {
    "monthly": os.environ.get("STRIPE_PRICE_BASIC_MONTHLY", ""),
    "annual": os.environ.get("STRIPE_PRICE_BASIC_ANNUAL", ""),
}

# --- Basic -> Pro upgrade (apps.billing.upgrade) ---
# Same Stripe account as everything else here (test mode), but these are
# the standalone Pro app's own Price IDs, not Basic's — an upgrade sends
# the customer through a real Pro Checkout Session. Get these from the
# Pro Render service's own env vars (STRIPE_PRICE_PRO_MONTHLY /
# STRIPE_PRICE_PRO_ANNUAL there) or the Stripe Dashboard.
STRIPE_PRICE_IDS_PRO = {
    "monthly": os.environ.get("STRIPE_PRICE_PRO_MONTHLY", ""),
    "annual": os.environ.get("STRIPE_PRICE_PRO_ANNUAL", ""),
}

# Where the "Welcome to Pro" post-upgrade page sends the customer to log
# in — a different Render service/domain from this one, so there's no
# way to carry their session over automatically. Their password hash is
# copied byte-for-byte during the migration, so their existing Basic
# password works immediately on Pro.
PRO_APP_LOGIN_URL = os.environ.get("PRO_APP_LOGIN_URL", "https://sitereviveiq-pro.onrender.com/accounts/login/")

# Scan-credit top-up (self-serve, one-time purchase — mode="payment", not
# a subscription). One shared price across every self-serve tier per
# Credit_System_Design.md's confirmed decision ("a shared price is fine
# ... keeps things fair across-the-board, especially if a user upgrades
# from basic to pro"): 10 credits for $25 — the exact same Stripe Price
# ID this codebase and Pro's both point at (same Stripe account, same
# as STRIPE_PRICE_IDS_PRO above). Enterprise has no equivalent — its
# top-up path is admin-console-manual only.
STRIPE_CREDIT_TOPUP_PRICE_ID = os.environ.get("STRIPE_CREDIT_TOPUP_PRICE_ID", "")
CREDIT_TOPUP_QUANTITY = 10  # credits granted per pack — must match the actual Stripe Price
