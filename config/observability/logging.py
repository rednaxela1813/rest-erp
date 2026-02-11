SENSITIVE_FRAGMENTS = (
    "password",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "secret",
    "access",
    "refresh",
)


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in SENSITIVE_FRAGMENTS)


def _mask_value(value):
    if isinstance(value, dict):
        return {k: _mask_value(v) if not _is_sensitive_key(k) else "***" for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_value(v) for v in value]
    return value


def mask_sensitive(_logger, _method_name, event_dict):
    """
    Structlog processor that masks common sensitive fields.
    """
    if not isinstance(event_dict, dict):
        return event_dict
    return _mask_value(event_dict)


class AppsOnlyFilter:
    """
    Limit DB log storage to application modules to reduce noise.
    """

    def filter(self, record):
        name = getattr(record, "name", "")
        return name.startswith("apps.") or name.startswith("config.") or name.startswith("core.")


import logging


class DBLogHandler(logging.Handler):
    """
    Logging handler that persists structured logs into the database.
    """

    def __init__(self, *args, **kwargs):
        super().__init__()

    def emit(self, record):
        try:
            from django.apps import apps as django_apps
            if not django_apps.ready:
                return
            LogEntry = django_apps.get_model("logs_dashboard", "LogEntry")
            if LogEntry is None:
                return

            import json

            raw_message = record.getMessage()
            payload = {}
            if isinstance(raw_message, str):
                try:
                    payload = json.loads(raw_message)
                except Exception:
                    payload = {"message": raw_message}
            elif isinstance(raw_message, dict):
                payload = raw_message
            else:
                payload = {"message": str(raw_message)}

            payload = mask_sensitive(None, None, payload)

            LogEntry.objects.create(
                level=getattr(record, "levelname", "INFO"),
                logger_name=getattr(record, "name", ""),
                event=str(payload.get("event", "")),
                message=str(payload.get("message", payload.get("event", ""))),
                request_id=str(payload.get("request_id", "")),
                org_id=str(payload.get("org_id", "")),
                user_id=str(payload.get("user_id", "")),
                path=str(payload.get("path", "")),
                method=str(payload.get("method", "")),
                task_id=str(payload.get("task_id", "")),
                task_name=str(payload.get("task_name", "")),
                raw=payload,
            )
        except Exception:
            # Never raise inside logging to avoid recursive failures.
            return
