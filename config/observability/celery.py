import structlog
from celery import signals


def _bind_task_context(task, task_id):
    headers = getattr(task.request, "headers", {}) or {}
    request_id = headers.get("request_id") or headers.get("X-Request-ID") or ""
    org_id = headers.get("org_id") or headers.get("X-ORG-ID") or ""

    structlog.contextvars.bind_contextvars(
        task_id=task_id,
        task_name=getattr(task, "name", ""),
        request_id=request_id,
        org_id=org_id,
    )


@signals.task_prerun.connect
def _task_prerun(*, task_id=None, task=None, **_kwargs):
    _bind_task_context(task, task_id)


@signals.task_postrun.connect
def _task_postrun(**_kwargs):
    structlog.contextvars.clear_contextvars()
