from __future__ import annotations

from django.conf import settings


def trigger_ekasa_processing(org_id: int) -> None:
    """Запускает обработку очереди eKasa команд если интеграция включена."""
    if not settings.EKASA_ENABLED:
        return

    from apps.payments.tasks import process_device_commands_ekasa

    process_device_commands_ekasa.delay(org_id=org_id, limit=50)
