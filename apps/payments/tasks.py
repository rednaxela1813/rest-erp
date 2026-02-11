from __future__ import annotations

import logging
from celery import shared_task
from django.conf import settings

from config.orgs.models import Organization
from django.db.models import F

from apps.payments.logic.device_commands import (
    ack_device_command,
    pull_device_commands,
    release_due_device_commands,
)
from apps.payments.streaming import publish_device_commands
from apps.payments.models import DeviceCommand, FiscalReceipt, OrderPayment
from apps.payments.providers import registry
from apps.payments.ekasa.client import EkasaClient
from apps.payments.ekasa.mapper import build_cash_register_request, extract_receipt_reference

logger = logging.getLogger(__name__)

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def dispatch_device_commands(self, org_id: int, limit: int = 50) -> dict:
    """
    Pull pending device commands and stream them via Redis.

    This task is intentionally small and idempotent:
    - Pull locks rows and marks them as SENT.
    - Publishing to Redis is safe because command idempotency keys are stable.
    """
    org = Organization.objects.filter(id=org_id).first()
    if not org:
        return {"published": 0, "command_ids": []}

    released = release_due_device_commands(org=org)
    commands = pull_device_commands(org=org, limit=limit)
    published = publish_device_commands(commands)

    return {
        "published": published,
        "released": released,
        "command_ids": [str(command.public_id) for command in commands],
    }


def _validate_mock_fiscal_payload(*, command: DeviceCommand) -> tuple[bool, str]:
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


def _hard_fail_command(*, command: DeviceCommand, error: str) -> None:
    command.status = DeviceCommand.Status.FAILED
    command.last_error = error
    command.retries = command.max_retries
    command.next_attempt_at = None
    command.save(
        update_fields=["status", "last_error", "retries", "next_attempt_at", "updated_at"]
    )


def _ensure_fiscal_receipt(*, command: DeviceCommand, raw_payload: dict | None = None) -> None:
    if command.command_type == DeviceCommand.Type.FISCALIZE_SALE:
        receipt_type = FiscalReceipt.Type.SALE
    elif command.command_type == DeviceCommand.Type.FISCALIZE_REFUND:
        receipt_type = FiscalReceipt.Type.REFUND
    elif command.command_type == DeviceCommand.Type.FISCALIZE_STORNO:
        receipt_type = FiscalReceipt.Type.STORNO
    else:
        return

    payment = command.payment
    order = command.order
    if not payment:
        return

    FiscalReceipt.objects.get_or_create(
        payment=payment,
        receipt_type=receipt_type,
        defaults={
            "org": payment.org,
            "order": order,
            "total": payment.amount,
            "tax_total": order.tax_total if order else 0,
            "currency": payment.currency,
            "raw_payload": raw_payload or {"mock": True, "command_id": str(command.public_id)},
        },
    )


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_device_commands_mock(self, org_id: int, limit: int = 50) -> dict:
    """
    Mock Local Agent:
    - Pulls pending device commands
    - Validates payload shape
    - ACKs success or FAILs with error
    - Can simulate offline fiscalization via FISCAL_MOCK_OFFLINE
    """
    org = Organization.objects.filter(id=org_id).first()
    if not org:
        return {"processed": 0, "ack": 0, "failed": 0, "reason": "org_not_found"}

    commands = pull_device_commands(org=org, limit=limit)
    if not commands:
        return {"processed": 0, "ack": 0, "failed": 0}

    offline = getattr(settings, "FISCAL_MOCK_OFFLINE", False)

    acked = 0
    failed = 0
    for command in commands:
        if offline and command.command_type.startswith("fiscalize_"):
            ack_device_command(
                command=command,
                status=DeviceCommand.Status.FAILED,
                error="offline",
            )
            failed += 1
            continue

        ok, error = _validate_mock_fiscal_payload(command=command)
        if not ok:
            _hard_fail_command(command=command, error=error)
            failed += 1
            continue

        if command.command_type.startswith("fiscalize_"):
            _ensure_fiscal_receipt(command=command)

        ack_device_command(
            command=command,
            status=DeviceCommand.Status.ACKED,
            error="",
        )
        acked += 1

    return {
        "processed": len(commands),
        "ack": acked,
        "failed": failed,
        "command_ids": [str(command.public_id) for command in commands],
    }


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def dispatch_device_commands_for_all_orgs(self, limit: int = 50) -> dict:
    """
    Periodic task to stream pending device commands for every org.

    This keeps offline fiscal receipts moving without manual triggers.
    """
    results = []
    for org_id in Organization.objects.values_list("id", flat=True):
        results.append(dispatch_device_commands.run(org_id=org_id, limit=limit))

    return {
        "orgs_processed": len(results),
        "results": results,
    }


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_device_commands_mock_for_all_orgs(self, limit: int = 50) -> dict:
    """
    Periodic mock-agent task for all orgs.
    """
    results = []
    for org_id in Organization.objects.values_list("id", flat=True):
        results.append(process_device_commands_mock.run(org_id=org_id, limit=limit))

    return {
        "orgs_processed": len(results),
        "results": results,
    }


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_device_commands_ekasa(self, org_id: int, limit: int = 50) -> dict:
    """
    eKasa Local Agent replacement:
    - Pulls fiscalize_* commands only
    - Registers receipt via eKasa Web API
    - ACKs or FAILs commands
    """
    org = Organization.objects.filter(id=org_id).first()
    if not org:
        return {"processed": 0, "ack": 0, "failed": 0, "reason": "org_not_found"}

    commands = pull_device_commands(
        org=org,
        limit=limit,
        command_types=[
            DeviceCommand.Type.FISCALIZE_SALE,
            DeviceCommand.Type.FISCALIZE_REFUND,
            DeviceCommand.Type.FISCALIZE_STORNO,
        ],
    )
    if not commands:
        return {"processed": 0, "ack": 0, "failed": 0}

    client = EkasaClient()

    acked = 0
    failed = 0
    for command in commands:
        try:
            payload = build_cash_register_request(
                command=command,
                cash_register_code=settings.EKASA_CASH_REGISTER_CODE,
            )
        except Exception as exc:
            logger.warning("eKasa payload build failed", extra={"command_id": str(command.public_id), "error": str(exc)})
            ack_device_command(
                command=command,
                status=DeviceCommand.Status.FAILED,
                error=str(exc),
            )
            failed += 1
            continue

        try:
            response = client.register_cash_register(payload=payload)
        except Exception as exc:
            logger.warning("eKasa request failed", extra={"command_id": str(command.public_id), "error": str(exc)})
            ack_device_command(
                command=command,
                status=DeviceCommand.Status.FAILED,
                error=str(exc),
            )
            failed += 1
            continue

        receipt_ref = extract_receipt_reference(response)
        merged_payload = dict(response or {})
        if receipt_ref:
            # Persist vendor receipt reference for future refunds/storno.
            merged_payload["receipt_id"] = receipt_ref
        _ensure_fiscal_receipt(command=command, raw_payload=merged_payload)
        if command.payment_id:
            # Mark fiscal status confirmed on successful external registration.
            command.payment.fiscal_status = OrderPayment.FiscalStatus.CONFIRMED
            command.payment.save(update_fields=["fiscal_status", "updated_at"])
        ack_device_command(
            command=command,
            status=DeviceCommand.Status.ACKED,
            error="",
        )
        acked += 1

    return {
        "processed": len(commands),
        "ack": acked,
        "failed": failed,
        "command_ids": [str(command.public_id) for command in commands],
    }


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_device_commands_ekasa_for_all_orgs(self, limit: int = 50) -> dict:
    """
    Periodic eKasa agent task for all orgs.
    """
    results = []
    for org_id in Organization.objects.values_list("id", flat=True):
        results.append(process_device_commands_ekasa.run(org_id=org_id, limit=limit))

    return {
        "orgs_processed": len(results),
        "results": results,
    }


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def reconcile_payment_capture(self, payment_id: int, timeout_s: int = 10) -> dict:
    """
    Reconcile capture status with the payment provider after outages.
    """
    payment = OrderPayment.objects.filter(id=payment_id).first()
    if not payment:
        return {"updated": False, "reason": "not_found"}

    provider = registry.get_provider_for_payment(payment)
    try:
        result = provider.capture_status(payment=payment, timeout_s=timeout_s)
    except NotImplementedError:
        return {"updated": False, "reason": "not_supported"}

    status = (result or {}).get("status")
    if status == "confirmed" and payment.capture_status != OrderPayment.CaptureStatus.CONFIRMED:
        payment.capture_status = OrderPayment.CaptureStatus.CONFIRMED
        payment.save(update_fields=["capture_status", "updated_at"])
        return {"updated": True, "capture_status": "confirmed"}
    if status == "failed" and payment.capture_status != OrderPayment.CaptureStatus.TIMEOUT:
        payment.capture_status = OrderPayment.CaptureStatus.TIMEOUT
        payment.failure_reason = "capture_reconcile_failed"
        payment.save(update_fields=["capture_status", "failure_reason", "updated_at"])
        return {"updated": True, "capture_status": "timeout"}

    return {"updated": False, "capture_status": status or ""}


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def reconcile_payment_fiscal_status(self, payment_id: int) -> dict:
    """
    Reconcile fiscalization status based on device command outcomes.
    """
    payment = OrderPayment.objects.filter(id=payment_id).first()
    if not payment:
        return {"updated": False, "reason": "not_found"}

    fiscal_commands = DeviceCommand.objects.filter(
        payment=payment,
        command_type__in=[
            DeviceCommand.Type.FISCALIZE_SALE,
            DeviceCommand.Type.FISCALIZE_REFUND,
            DeviceCommand.Type.FISCALIZE_STORNO,
        ],
    )
    if not fiscal_commands.exists():
        return {"updated": False, "reason": "no_fiscal_commands"}

    if fiscal_commands.filter(status=DeviceCommand.Status.ACKED).exists():
        if payment.fiscal_status != OrderPayment.FiscalStatus.CONFIRMED:
            payment.fiscal_status = OrderPayment.FiscalStatus.CONFIRMED
            payment.save(update_fields=["fiscal_status", "updated_at"])
            return {"updated": True, "fiscal_status": "confirmed"}
        return {"updated": False, "fiscal_status": "confirmed"}

    if fiscal_commands.filter(status__in=[DeviceCommand.Status.PENDING, DeviceCommand.Status.SENT]).exists():
        if payment.fiscal_status != OrderPayment.FiscalStatus.PENDING:
            payment.fiscal_status = OrderPayment.FiscalStatus.PENDING
            payment.save(update_fields=["fiscal_status", "updated_at"])
            return {"updated": True, "fiscal_status": "pending"}
        return {"updated": False, "fiscal_status": "pending"}

    has_retryable_failures = fiscal_commands.filter(
        status=DeviceCommand.Status.FAILED,
        retries__lt=F("max_retries"),
    ).exists()
    if has_retryable_failures:
        if payment.fiscal_status != OrderPayment.FiscalStatus.FAILED:
            payment.fiscal_status = OrderPayment.FiscalStatus.FAILED
            payment.save(update_fields=["fiscal_status", "updated_at"])
            return {"updated": True, "fiscal_status": "failed"}
        return {"updated": False, "fiscal_status": "failed"}

    # All fiscal commands exhausted retries.
    if payment.fiscal_status != OrderPayment.FiscalStatus.FAILED:
        payment.fiscal_status = OrderPayment.FiscalStatus.FAILED
        payment.save(update_fields=["fiscal_status", "updated_at"])
        return {"updated": True, "fiscal_status": "failed"}
    return {"updated": False, "fiscal_status": "failed"}


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def reconcile_payment_fiscal_status_for_all_orgs(self, limit: int = 200) -> dict:
    """
    Periodic reconciler for fiscal status.

    We only target payments that have fiscal commands stuck in PENDING/SENT/FAILED.
    """
    fiscal_types = [
        DeviceCommand.Type.FISCALIZE_SALE,
        DeviceCommand.Type.FISCALIZE_REFUND,
        DeviceCommand.Type.FISCALIZE_STORNO,
    ]
    candidate_payments = (
        OrderPayment.objects
        .filter(device_commands__command_type__in=fiscal_types)
        .filter(device_commands__status__in=[
            DeviceCommand.Status.PENDING,
            DeviceCommand.Status.SENT,
            DeviceCommand.Status.FAILED,
        ])
        .distinct()
        .order_by("id")[:limit]
    )

    processed = 0
    updated = 0
    for payment in candidate_payments:
        result = reconcile_payment_fiscal_status.run(payment_id=payment.id)
        processed += 1
        if result.get("updated"):
            updated += 1

    return {
        "processed": processed,
        "updated": updated,
        "payment_ids": [p.id for p in candidate_payments],
    }
