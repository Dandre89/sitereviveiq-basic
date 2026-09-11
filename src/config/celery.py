import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("sitereviveiq")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "check-scheduled-scans-hourly": {
        "task": "apps.monitoring.tasks.check_scheduled_scans",
        "schedule": 3600.0,  # every hour, on the hour is not required — just every 3600s
    },
}
