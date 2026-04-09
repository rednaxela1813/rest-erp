from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
import structlog

from apps.payments.logic.enqueue_device_commands import enqueue_payment_commands
from apps.payments.models import FiscalReceipt, OrderPayment
from apps.payments.providers import registry
from apps.orders.logic.finalize_paid_order import finalize_paid_order
from apps.accounting.logic.record_sale import record_sale

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

        if not requires_post_fiscal_finalization:
            finalize_paid_order(order=payment.order, actor=actor)
            record_sale(order=payment.order, tender=payment.tender)

        if payment.tender == OrderPayment.Tender.CARD and not requires_post_fiscal_finalization:
            FiscalReceipt.objects.get_or_create(
                payment=payment,
                receipt_type=FiscalReceipt.Type.SALE,
                defaults={
                    "org": payment.org,
                    "order": payment.order,
                    "total": payment.amount,
                    "tax_total": payment.order.tax_total,
                    "currency": payment.currency,
                    "raw_payload": payment.raw_provider_payload,
                },
            )

        # Enqueue device commands for local agent processing.
        # KOT is only needed if the order produced kitchen tickets.
        include_kot = payment.order.kitchen_tickets.exists()
        enqueue_payment_commands(payment=payment, include_kot=include_kot)
        if requires_post_fiscal_finalization:
            from apps.payments.tasks import process_device_commands_ekasa
            process_device_commands_ekasa.delay(org_id=payment.org_id, limit=50)

    logger.info(
        "payment_capture_succeeded",
        payment_id=str(payment.public_id),
        order_id=str(payment.order.public_id),
        fiscal_receipt_created=payment.tender == OrderPayment.Tender.CARD and not _requires_post_fiscal_finalization(payment=payment),
    )
    return payment
