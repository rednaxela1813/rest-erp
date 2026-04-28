# rest-erp/apps/payments/logic/capture_payment.py
from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
import structlog

from apps.payments.logic.post_capture import handle_captured_payment
from apps.payments.models import OrderPayment
from apps.payments.providers import registry

logger = structlog.get_logger(__name__)


def _requires_post_fiscal_finalization(*, payment: OrderPayment) -> bool:
    if not settings.EKASA_ENABLED:
        return False
    return payment.terminal_id is not None or payment.provider == "ekasa"


def capture_payment(*, payment: OrderPayment, actor=None, timeout_s: int = 30) -> OrderPayment:
    logger.info(
        "payment_capture_started",
        payment_id=str(payment.public_id),
        order_id=str(payment.order.public_id),
        amount=str(payment.amount),
        tender=payment.tender,
        provider=payment.provider,
    )
    if payment.status != OrderPayment.Status.AUTHORIZED:
        raise ValidationError({"status": ["Payment is not authorized."]})

    provider = registry.get_provider_for_payment(payment)
    payload = provider.capture(payment=payment, timeout_s=timeout_s)

    with transaction.atomic():
        payment.status = OrderPayment.Status.CAPTURED
        payment.captured_at = timezone.now()
        requires_post_fiscal_finalization = _requires_post_fiscal_finalization(payment=payment)
        if requires_post_fiscal_finalization:
            payment.fiscal_status = OrderPayment.FiscalStatus.PENDING
        payment.raw_provider_payload = payload
        if requires_post_fiscal_finalization:
            payment.save(
                update_fields=[
                    "status",
                    "captured_at",
                    "fiscal_status",
                    "raw_provider_payload",
                    "updated_at",
                ]
            )
        else:
            payment.save(update_fields=["status", "captured_at", "raw_provider_payload", "updated_at"])

        handle_captured_payment(
            payment=payment,
            actor=actor,
            requires_post_fiscal_finalization=requires_post_fiscal_finalization,
        )

    logger.info(
        "payment_capture_succeeded",
        payment_id=str(payment.public_id),
        order_id=str(payment.order.public_id),
        fiscal_receipt_created=payment.tender == OrderPayment.Tender.CARD
        and not _requires_post_fiscal_finalization(payment=payment),
    )
    return payment
