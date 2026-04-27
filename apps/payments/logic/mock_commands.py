from __future__ import annotations

from config.orgs.models import Organization

from apps.payments.logic.device_commands import ack_device_command, pull_device_commands
from apps.payments.logic.fiscal_receipts import ensure_fiscal_receipt
from apps.payments.models import DeviceCommand


def process_mock_device_commands(*, org_id: int, limit: int, fiscal_mock_offline: bool, logger) -> dict:
    """
    Mock Local Agent:
    - Pulls pending device commands
    - Validates payload shape
    - ACKs success or FAILs with error
    - Can simulate offline fiscalization via FISCAL_MOCK_OFFLINE
    """
    logger.info("task_process_device_commands_mock_started", org_id=str(org_id), limit=limit)
    org = Organization.objects.filter(id=org_id).first()
    if not org:
        logger.warning("task_process_device_commands_mock_org_not_found", org_id=str(org_id))
        return {"processed": 0, "ack": 0, "failed": 0, "reason": "org_not_found"}

    commands = pull_device_commands(org=org, limit=limit)
    if not commands:
        logger.info("task_process_device_commands_mock_no_commands", org_id=str(org_id))
        return {"processed": 0, "ack": 0, "failed": 0}

    acked = 0
    failed = 0
    for command in commands:
        if fiscal_mock_offline and command.command_type.startswith("fiscalize_"):
            logger.warning(
                "task_process_device_commands_mock_offline_fail",
                org_id=str(org_id),
                command_id=str(command.public_id),
                command_type=command.command_type,
            )
            ack_device_command(
                command=command,
                status=DeviceCommand.Status.FAILED,
                error="offline",
            )
            failed += 1
            continue

        ok, error = validate_mock_fiscal_payload(command=command)
        if not ok:
            logger.warning(
                "task_process_device_commands_mock_validation_failed",
                org_id=str(org_id),
                command_id=str(command.public_id),
                command_type=command.command_type,
                error=error,
            )
            hard_fail_command(command=command, error=error)
            failed += 1
            continue

        if command.command_type.startswith("fiscalize_"):
            ensure_fiscal_receipt(command=command)

        ack_device_command(
            command=command,
            status=DeviceCommand.Status.ACKED,
            error="",
        )
        acked += 1

    result = {
        "processed": len(commands),
        "ack": acked,
        "failed": failed,
        "command_ids": [str(command.public_id) for command in commands],
    }
    logger.info(
        "task_process_device_commands_mock_succeeded",
        org_id=str(org_id),
        processed=result["processed"],
        ack=acked,
        failed=failed,
        command_ids=result["command_ids"],
    )
    return result


def validate_mock_fiscal_payload(*, command: DeviceCommand) -> tuple[bool, str]:
    payload = command.payload or {}

    required_fields = ["order_id", "payment_id", "amount", "currency"]
    missing = [field for field in required_fields if not payload.get(field)]
    if missing:
        return False, f"validation_error: missing_fields={','.join(missing)}"

    if command.command_type in {
        DeviceCommand.Type.FISCALIZE_REFUND,
        DeviceCommand.Type.FISCALIZE_STORNO,
    } and not payload.get("receipt_id"):
        return False, "validation_error: missing_receipt_id"

    items = payload.get("items")
    if items is not None:
        if not isinstance(items, list):
            return False, "validation_error: items_not_list"
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                return False, f"validation_error: item_{index}_not_object"
            for field in ["name", "qty", "unit_price", "tax_rate"]:
                if field not in item:
                    return False, f"validation_error: item_{index}_missing_{field}"

    return True, ""


def hard_fail_command(*, command: DeviceCommand, error: str) -> None:
    command.status = DeviceCommand.Status.FAILED
    command.last_error = error
    command.retries = command.max_retries
    command.next_attempt_at = None
    command.save(update_fields=["status", "last_error", "retries", "next_attempt_at", "updated_at"])
