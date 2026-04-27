from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import ValidationError
import structlog

from apps.accounting.logic.record_refund import record_refund
from apps.orders.logic.cancel_order import cancel_order
from apps.orders.models import Order
from apps.payments.logic.enqueue_device_commands import enqueue_refund_commands, enqueue_storno_commands
from apps.payments.models import FiscalReceipt, OrderPayment

logger = structlog.get_logger(__name__)


def refund_paid_order(*, order: Order, actor=None) -> FiscalReceipt:
    """
    Refund a paid order.

    Business rules:
    - Only PAID orders can be refunded.
    - Refund is idempotent: if already refunded, return existing receipt.
    - Refund cancels the order and restores stock through cancel_order.
    - Refund creates a fiscal receipt linked to the captured payment.
    - Refund enqueues device commands for Local Agent.
    """
    if order.status == Order.STATUS_CANCELLED:
        existing = (
            FiscalReceipt.objects.filter(order=order, receipt_type=FiscalReceipt.Type.REFUND)
            .order_by("-created_at")
            .first()
        )
        if existing:
            return existing
        raise ValidationError({"order": ["Order is already cancelled."]})

    if order.status != Order.STATUS_PAID:
        raise ValidationError({"order": ["Only paid orders can be refunded."]})

    payment = order.payments.filter(status=OrderPayment.Status.CAPTURED).order_by("-created_at").first()
    if payment is None:
        raise ValidationError({"payment": ["Captured payment is required for refund."]})

    with transaction.atomic():
        cancelled = cancel_order(order=order, actor=actor)
        record_refund(order=cancelled, tender=payment.tender)

        receipt, _created = FiscalReceipt.objects.get_or_create(
            payment=payment,
            receipt_type=FiscalReceipt.Type.REFUND,
            defaults={
                "org": cancelled.org,
                "order": cancelled,
                "total": payment.amount,
                "tax_total": cancelled.tax_total,
                "currency": payment.currency,
                "raw_payload": {},
            },
        )

        receipt_ref = _sale_receipt_reference(payment=payment)
        enqueue_refund_commands(
            payment=payment,
            receipt_public_id=receipt_ref or str(receipt.public_id),
        )

        logger.info(
            "order_refunded",
            order_id=str(cancelled.public_id),
            payment_id=str(payment.public_id),
            receipt_ref=receipt_ref or "",
            actor_id=str(actor.id) if actor else "",
        )

    return receipt


def storno_paid_order(*, order: Order, actor=None) -> FiscalReceipt:
    """
    Storno a paid order.

    Business rules:
    - Only PAID orders can be stornoed.
    - Storno is idempotent: if already stornoed, return existing receipt.
    - Storno cancels the order and restores stock.
    - Storno creates a fiscal receipt linked to captured payment.
    - Storno enqueues device commands for Local Agent execution.
    """
    if order.status == Order.STATUS_CANCELLED:
        existing = (
            FiscalReceipt.objects.filter(order=order, receipt_type=FiscalReceipt.Type.STORNO)
            .order_by("-created_at")
            .first()
        )
        if existing:
            return existing
        raise ValidationError({"order": ["Order is already cancelled."]})

    if order.status != Order.STATUS_PAID:
        raise ValidationError({"order": ["Only paid orders can be stornoed."]})

    payment = order.payments.filter(status=OrderPayment.Status.CAPTURED).order_by("-created_at").first()
    if payment is None:
        raise ValidationError({"payment": ["Captured payment is required for storno."]})

    with transaction.atomic():
        cancelled = cancel_order(order=order, actor=actor)

        receipt, _created = FiscalReceipt.objects.get_or_create(
            payment=payment,
            receipt_type=FiscalReceipt.Type.STORNO,
            defaults={
                "org": cancelled.org,
                "order": cancelled,
                "total": payment.amount,
                "tax_total": cancelled.tax_total,
                "currency": payment.currency,
                "raw_payload": {},
            },
        )

        receipt_ref = _sale_receipt_reference(payment=payment)
        enqueue_storno_commands(
            payment=payment,
            receipt_public_id=receipt_ref or str(receipt.public_id),
        )

        logger.info(
            "order_storno",
            order_id=str(cancelled.public_id),
            payment_id=str(payment.public_id),
            receipt_ref=receipt_ref or "",
            actor_id=str(actor.id) if actor else "",
        )

    return receipt


def _sale_receipt_reference(*, payment: OrderPayment) -> str:
    sale_receipt = (
        FiscalReceipt.objects.filter(payment=payment, receipt_type=FiscalReceipt.Type.SALE)
        .order_by("-created_at")
        .first()
    )
    if not sale_receipt:
        return ""
    return (sale_receipt.raw_payload or {}).get("receipt_id") or ""
