from celery import shared_task


@shared_task(bind=True, max_retries=0)
def run_scan_task(self, scan_id: str) -> None:
    """
    Entry point Celery calls. max_retries=0 is deliberate: a failed scan
    should land in a clear failed state (section 8.2), not silently retry
    against a target that may not want repeated automated requests.
    """
    from .services import execute_scan

    execute_scan(scan_id)
