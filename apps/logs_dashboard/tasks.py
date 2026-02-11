from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.logs_dashboard.models import LogEntry


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def purge_old_logs(self, days: int = 30) -> dict:
    """
    Purge old log entries to keep DB size under control.
    """
    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = LogEntry.objects.filter(created_at__lt=cutoff).delete()
    return {"deleted": deleted, "cutoff": cutoff.isoformat()}
