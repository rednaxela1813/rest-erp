from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.orders.logic.cancel_order import cancel_order
from apps.orders.models import Order
from apps.payments.logic.enqueue_device_commands import enqueue_refund_commands
from apps.payments.models import FiscalReceipt, OrderPayment


def refund_paid_order(*, order: Order, actor=None) -> FiscalReceipt:
    """
    Use-case: refund a paid order.

    Business rules:
    - Only PAID orders can be refunded.
    - Refund is idempotent: if already refunded, return existing receipt.
    - Refund triggers order cancellation + stock return (via cancel_order).
    - Refund creates a fiscal receipt of type REFUND linked to the captured payment.
    - Refund enqueues device commands for Local Agent.
    """
    # Idempotency: if order already cancelled and refund receipt exists, return it.
    if order.status == Order.STATUS_CANCELLED:
        existing = (
            FiscalReceipt.objects
            .filter(order=order, receipt_type=FiscalReceipt.Type.REFUND)
            .order_by("-created_at")
            .first()
        )
        if existing:
            return existing
        raise ValidationError({"order": ["Order is already cancelled."]})

    if order.status != Order.STATUS_PAID:
        raise ValidationError({"order": ["Only paid orders can be refunded."]})

    # Find the latest captured payment to link refund receipt.
    payment = (
        order.payments.filter(status=OrderPayment.Status.CAPTURED)
        .order_by("-created_at")
        .first()
    )
    if payment is None:
        raise ValidationError({"payment": ["Captured payment is required for refund."]})

    with transaction.atomic():
        # Cancel the order and revert stock atomically.
        cancelled = cancel_order(order=order, actor=actor)

        # Create (or reuse) refund fiscal receipt for this payment.
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

        # Enqueue commands so Local Agent can execute refund + print.
        enqueue_refund_commands(payment=payment, receipt_public_id=str(receipt.public_id))

    return receipt
