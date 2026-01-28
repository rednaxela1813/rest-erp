from __future__ import annotations

from celery import shared_task

from config.orgs.models import Organization
from django.db.models import F

from apps.payments.logic.device_commands import pull_device_commands, release_due_device_commands
from apps.payments.streaming import publish_device_commands
from apps.payments.models import DeviceCommand, OrderPayment
from apps.payments.providers import registry


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
