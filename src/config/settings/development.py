from .base import *  # noqa: F401,F403

DEBUG = True
SECRET_KEY = SECRET_KEY or "dev-only-insecure-key-do-not-use-in-production"  # noqa: F405
ALLOWED_HOSTS = ["*"]

DATABASES["default"]["HOST"] = "postgres"  # noqa: F405
CELERY_BROKER_URL = "redis://redis:6379/0"  # noqa: F405
CELERY_RESULT_BACKEND = "redis://redis:6379/0"  # noqa: F405

STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"  # noqa: F405
