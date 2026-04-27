from __future__ import annotations

from collections.abc import Callable

from config.orgs.models import Organization

from apps.payments.logic.device_commands import pull_device_commands, release_due_device_commands
from apps.payments.models import DeviceCommand


def dispatch_pending_device_commands(
    *,
    org_id: int,
    limit: int,
    ekasa_enabled: bool,
    publisher: Callable,
    logger,
) -> dict:
    """
    Pull pending device commands and stream them via Redis.

    This is intentionally idempotent:
    - Pull locks rows and marks them as SENT.
    - Publishing to Redis is safe because command idempotency keys are stable.
    """
    logger.info("task_dispatch_device_commands_started", org_id=str(org_id), limit=limit)
    org = Organization.objects.filter(id=org_id).first()
    if not org:
        logger.warning("task_dispatch_device_commands_org_not_found", org_id=str(org_id))
        return {"published": 0, "command_ids": []}

    released = release_due_device_commands(org=org)
    command_types: list[str] | None = None
    if ekasa_enabled:
        command_types = [
            str(DeviceCommand.Type.PAYMENT_CAPTURE),
            str(DeviceCommand.Type.PRINT_RECEIPT),
            str(DeviceCommand.Type.PRINT_KOT),
        ]
    commands = pull_device_commands(org=org, limit=limit, command_types=command_types)
    published = publisher(commands)

    result = {
        "published": published,
        "released": released,
        "command_ids": [str(command.public_id) for command in commands],
    }
    logger.info(
        "task_dispatch_device_commands_succeeded",
        org_id=str(org_id),
        published=published,
        released=released,
        command_ids=result["command_ids"],
    )
    return result
