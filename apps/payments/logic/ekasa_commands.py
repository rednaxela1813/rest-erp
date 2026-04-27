from __future__ import annotations

from collections.abc import Callable

from django.db import transaction

from config.orgs.models import Organization

from apps.payments.ekasa.mapper import build_cash_register_request, extract_receipt_reference
from apps.payments.logic.device_commands import ack_device_command, pull_device_commands, release_due_device_commands
from apps.payments.logic.fiscal_receipts import ensure_fiscal_receipt, finalize_sale_after_fiscal_confirmation
from apps.payments.models import DeviceCommand, OrderPayment


EKASA_COMMAND_TYPES: list[str] = [
    str(DeviceCommand.Type.FISCALIZE_SALE),
    str(DeviceCommand.Type.FISCALIZE_REFUND),
    str(DeviceCommand.Type.FISCALIZE_STORNO),
]


def process_ekasa_device_commands(
    *,
    org_id: int,
    limit: int,
    cash_register_code: str,
    client_factory: Callable,
    logger,
) -> dict:
    logger.info("task_process_device_commands_ekasa_started", org_id=str(org_id), limit=limit)
    org = Organization.objects.filter(id=org_id).first()
    if not org:
        logger.warning("task_process_device_commands_ekasa_org_not_found", org_id=str(org_id))
        return {"processed": 0, "ack": 0, "failed": 0, "reason": "org_not_found"}

    released = release_due_device_commands(org=org)
    commands = pull_device_commands(
        org=org,
        limit=limit,
        command_types=EKASA_COMMAND_TYPES,
    )
    if not commands:
        logger.info("task_process_device_commands_ekasa_no_commands", org_id=str(org_id))
        return {"processed": 0, "ack": 0, "failed": 0, "released": released}

    client = client_factory()

    acked = 0
    failed = 0
    for command in commands:
        try:
            payload = build_cash_register_request(
                command=command,
                cash_register_code=cash_register_code,
            )
        except Exception as exc:
            _fail_command(
                command=command,
                status_event="task_process_device_commands_ekasa_payload_build_failed",
                org_id=org_id,
                error=str(exc),
                logger=logger,
            )
            failed += 1
            continue

        try:
            response = client.register_cash_register(payload=payload)
        except Exception as exc:
            _fail_command(
                command=command,
                status_event="task_process_device_commands_ekasa_request_failed",
                org_id=org_id,
                error=str(exc),
                logger=logger,
            )
            failed += 1
            continue

        receipt_ref = extract_receipt_reference(response)
        merged_payload = dict(response or {})
        if receipt_ref:
            merged_payload["receipt_id"] = receipt_ref
        with transaction.atomic():
            ensure_fiscal_receipt(command=command, raw_payload=merged_payload)
            payment = command.payment
            if payment is not None:
                payment.fiscal_status = OrderPayment.FiscalStatus.CONFIRMED
                payment.failure_reason = ""
                payment.save(update_fields=["fiscal_status", "failure_reason", "updated_at"])
                if command.command_type == DeviceCommand.Type.FISCALIZE_SALE:
                    finalize_sale_after_fiscal_confirmation(payment=payment)
        ack_device_command(
            command=command,
            status=DeviceCommand.Status.ACKED,
            error="",
        )
        logger.info(
            "task_process_device_commands_ekasa_command_acked",
            org_id=str(org_id),
            command_id=str(command.public_id),
            receipt_id=receipt_ref or "",
        )
        acked += 1

    result = {
        "processed": len(commands),
        "ack": acked,
        "failed": failed,
        "released": released,
        "command_ids": [str(command.public_id) for command in commands],
    }
    logger.info(
        "task_process_device_commands_ekasa_succeeded",
        org_id=str(org_id),
        processed=result["processed"],
        ack=acked,
        failed=failed,
        command_ids=result["command_ids"],
    )
    return result


def _fail_command(*, command: DeviceCommand, status_event: str, org_id: int, error: str, logger) -> None:
    logger.warning(
        status_event,
        org_id=str(org_id),
        command_id=str(command.public_id),
        error=error,
    )
    payment = command.payment
    if payment is not None:
        payment.fiscal_status = OrderPayment.FiscalStatus.FAILED
        payment.failure_reason = error
        payment.save(update_fields=["fiscal_status", "failure_reason", "updated_at"])
    ack_device_command(
        command=command,
        status=DeviceCommand.Status.FAILED,
        error=error,
    )
