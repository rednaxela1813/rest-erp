from __future__ import annotations

from collections.abc import Callable

from django.db.models import F

from apps.payments.logic.ekasa_commands import EKASA_COMMAND_TYPES
from apps.payments.models import DeviceCommand, OrderPayment


def reconcile_capture_status(*, payment_id: int, timeout_s: int, provider_registry, logger) -> dict:
    logger.info("task_reconcile_payment_capture_started", payment_id=str(payment_id), timeout_s=timeout_s)
    payment = OrderPayment.objects.filter(id=payment_id).first()
    if not payment:
        logger.warning("task_reconcile_payment_capture_not_found", payment_id=str(payment_id))
        return {"updated": False, "reason": "not_found"}

    provider = provider_registry.get_provider_for_payment(payment)
    try:
        result = provider.capture_status(payment=payment, timeout_s=timeout_s)
    except NotImplementedError:
        logger.info(
            "task_reconcile_payment_capture_not_supported",
            payment_id=str(payment_id),
            provider=payment.provider,
        )
        return {"updated": False, "reason": "not_supported"}

    status = (result or {}).get("status")
    if status == "confirmed" and payment.capture_status != OrderPayment.CaptureStatus.CONFIRMED:
        payment.capture_status = OrderPayment.CaptureStatus.CONFIRMED
        payment.save(update_fields=["capture_status", "updated_at"])
        logger.info("task_reconcile_payment_capture_confirmed", payment_id=str(payment_id))
        return {"updated": True, "capture_status": "confirmed"}
    if status == "failed" and payment.capture_status != OrderPayment.CaptureStatus.TIMEOUT:
        payment.capture_status = OrderPayment.CaptureStatus.TIMEOUT
        payment.failure_reason = "capture_reconcile_failed"
        payment.save(update_fields=["capture_status", "failure_reason", "updated_at"])
        logger.warning("task_reconcile_payment_capture_failed", payment_id=str(payment_id))
        return {"updated": True, "capture_status": "timeout"}

    logger.info(
        "task_reconcile_payment_capture_no_change",
        payment_id=str(payment_id),
        capture_status=status or "",
    )
    return {"updated": False, "capture_status": status or ""}


def reconcile_fiscal_status(*, payment_id: int, logger) -> dict:
    logger.info("task_reconcile_payment_fiscal_started", payment_id=str(payment_id))
    payment = OrderPayment.objects.filter(id=payment_id).first()
    if not payment:
        logger.warning("task_reconcile_payment_fiscal_not_found", payment_id=str(payment_id))
        return {"updated": False, "reason": "not_found"}

    fiscal_commands = DeviceCommand.objects.filter(
        payment=payment,
        command_type__in=EKASA_COMMAND_TYPES,
    )
    if not fiscal_commands.exists():
        logger.info("task_reconcile_payment_fiscal_no_commands", payment_id=str(payment_id))
        return {"updated": False, "reason": "no_fiscal_commands"}

    if fiscal_commands.filter(status=DeviceCommand.Status.ACKED).exists():
        if payment.fiscal_status != OrderPayment.FiscalStatus.CONFIRMED:
            payment.fiscal_status = OrderPayment.FiscalStatus.CONFIRMED
            payment.save(update_fields=["fiscal_status", "updated_at"])
            logger.info("task_reconcile_payment_fiscal_confirmed", payment_id=str(payment_id))
            return {"updated": True, "fiscal_status": "confirmed"}
        logger.info("task_reconcile_payment_fiscal_already_confirmed", payment_id=str(payment_id))
        return {"updated": False, "fiscal_status": "confirmed"}

    if fiscal_commands.filter(status__in=[DeviceCommand.Status.PENDING, DeviceCommand.Status.SENT]).exists():
        if payment.fiscal_status != OrderPayment.FiscalStatus.PENDING:
            payment.fiscal_status = OrderPayment.FiscalStatus.PENDING
            payment.save(update_fields=["fiscal_status", "updated_at"])
            logger.info("task_reconcile_payment_fiscal_pending", payment_id=str(payment_id))
            return {"updated": True, "fiscal_status": "pending"}
        logger.info("task_reconcile_payment_fiscal_already_pending", payment_id=str(payment_id))
        return {"updated": False, "fiscal_status": "pending"}

    has_retryable_failures = fiscal_commands.filter(
        status=DeviceCommand.Status.FAILED,
        retries__lt=F("max_retries"),
    ).exists()
    if has_retryable_failures:
        if payment.fiscal_status != OrderPayment.FiscalStatus.FAILED:
            payment.fiscal_status = OrderPayment.FiscalStatus.FAILED
            payment.save(update_fields=["fiscal_status", "updated_at"])
            logger.warning("task_reconcile_payment_fiscal_failed_retryable", payment_id=str(payment_id))
            return {"updated": True, "fiscal_status": "failed"}
        logger.warning("task_reconcile_payment_fiscal_already_failed_retryable", payment_id=str(payment_id))
        return {"updated": False, "fiscal_status": "failed"}

    if payment.fiscal_status != OrderPayment.FiscalStatus.FAILED:
        payment.fiscal_status = OrderPayment.FiscalStatus.FAILED
        payment.save(update_fields=["fiscal_status", "updated_at"])
        logger.warning("task_reconcile_payment_fiscal_failed_exhausted", payment_id=str(payment_id))
        return {"updated": True, "fiscal_status": "failed"}
    logger.warning("task_reconcile_payment_fiscal_already_failed_exhausted", payment_id=str(payment_id))
    return {"updated": False, "fiscal_status": "failed"}


def reconcile_fiscal_status_for_all_orgs(*, limit: int, reconcile_payment: Callable, logger) -> dict:
    logger.info("task_reconcile_payment_fiscal_for_all_orgs_started", limit=limit)
    candidate_payments = (
        OrderPayment.objects.filter(device_commands__command_type__in=EKASA_COMMAND_TYPES)
        .filter(
            device_commands__status__in=[
                DeviceCommand.Status.PENDING,
                DeviceCommand.Status.SENT,
                DeviceCommand.Status.FAILED,
            ]
        )
        .distinct()
        .order_by("id")[:limit]
    )

    processed = 0
    updated = 0
    for payment in candidate_payments:
        result = reconcile_payment(payment_id=payment.id)
        processed += 1
        if result.get("updated"):
            updated += 1

    result = {
        "processed": processed,
        "updated": updated,
        "payment_ids": [p.id for p in candidate_payments],
    }
    logger.info(
        "task_reconcile_payment_fiscal_for_all_orgs_succeeded",
        processed=processed,
        updated=updated,
    )
    return result
