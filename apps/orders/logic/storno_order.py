from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import ValidationError
import structlog

from apps.orders.logic.cancel_order import cancel_order
from apps.orders.models import Order
from apps.payments.logic.enqueue_device_commands import enqueue_storno_commands
from apps.payments.models import FiscalReceipt, OrderPayment

logger = structlog.get_logger(__name__)


def storno_paid_order(*, order: Order, actor=None) -> FiscalReceipt:
    """
    Use-case: storno a paid order.

    Business rules:
    - Only PAID orders can be stornoed.
    - Storno is idempotent: if already stornoed, return existing receipt.
    - Storno cancels the order (paid -> cancelled) and restores stock.
    - Storno creates a fiscal receipt of type STORNO linked to captured payment.
    - Storno enqueues device commands for Local Agent execution.
    """
    # Idempotency: if order is already cancelled and storno receipt exists, return it.
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

    # Find the latest captured payment to link storno receipt.
    payment = order.payments.filter(status=OrderPayment.Status.CAPTURED).order_by("-created_at").first()
    if payment is None:
        raise ValidationError({"payment": ["Captured payment is required for storno."]})

    with transaction.atomic():
        # Cancel the order and revert stock atomically.
        cancelled = cancel_order(order=order, actor=actor)

        # Create (or reuse) storno fiscal receipt for this payment.
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

        # Use the original eKasa receipt reference if available.
        sale_receipt = (
            FiscalReceipt.objects.filter(payment=payment, receipt_type=FiscalReceipt.Type.SALE)
            .order_by("-created_at")
            .first()
        )
        receipt_ref = ""
        if sale_receipt:
            receipt_ref = (sale_receipt.raw_payload or {}).get("receipt_id") or ""

        # Enqueue commands so Local Agent can execute storno + print.
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
