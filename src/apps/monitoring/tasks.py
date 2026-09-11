"""
Runs on an hourly Celery Beat schedule (see config/celery.py). Doesn't
scan everything every hour — it checks each monitored website's own
frequency and last scan time, and only triggers a scan when one is
actually due. A website with no completed scan yet is always due.
"""
import datetime

from celery import shared_task
from django.utils import timezone

FREQUENCY_INTERVALS = {
    "weekly": datetime.timedelta(days=7),
    "monthly": datetime.timedelta(days=30),
}


@shared_task
def check_scheduled_scans() -> int:
    from apps.scans.models import Scan
    from apps.scans.services import DuplicateActiveScanError, start_scan
    from apps.scans.tasks import run_scan_task
    from apps.websites.models import Website

    triggered = 0
    monitored = Website.objects.exclude(
        monitoring_frequency=Website.MonitoringFrequency.NONE
    ).exclude(status=Website.Status.ARCHIVED)

    for website in monitored:
        interval = FREQUENCY_INTERVALS.get(website.monitoring_frequency)
        if not interval:
            continue

        last_scan = website.scans.filter(status__in=Scan.TERMINAL_STATUSES).order_by(
            "-created_at"
        ).first()
        is_due = last_scan is None or (timezone.now() - last_scan.created_at) >= interval
        if not is_due:
            continue

        try:
            scan = start_scan(website, requested_by=None, trigger=Scan.Trigger.SCHEDULED)
        except DuplicateActiveScanError:
            continue

        task = run_scan_task.delay(str(scan.id))
        scan.celery_task_id = task.id
        scan.save(update_fields=["celery_task_id"])
        triggered += 1

    return triggered
