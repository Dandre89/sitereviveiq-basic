"""
Runs on a daily Celery Beat schedule (see config/celery.py). See
apps.billing.credits.reset_due_cycles for what actually happens to each
workspace's balance — this task is just the schedule trigger.
"""
from celery import shared_task


@shared_task
def reset_due_credit_cycles() -> int:
    from .credits import reset_due_cycles

    return reset_due_cycles()
