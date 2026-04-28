from __future__ import annotations

from rest_framework.exceptions import ValidationError

from apps.orders.logic.cancel_draft_order import cancel_draft_order
from apps.orders.logic.cancel_order import cancel_order
from apps.orders.models import Order


def add_item_to_order_from_api(*, order: Order, serializer, logger) -> None:
    if order.status != Order.STATUS_DRAFT:
        logger.warning(
            "order_item_create_rejected_non_draft_order",
            order_id=str(order.public_id),
            order_status=order.status,
        )
        raise ValidationError({"order": "Cannot modify items for non-draft order."})

    serializer.save(order=order)
    order.recompute_totals()
    order.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])


def update_order_from_api(*, order: Order, serializer, actor, logger) -> None:
    if "status" not in serializer.validated_data:
        serializer.save()
        return

    new_status = serializer.validated_data["status"]
    old_status = order.status

    if new_status == Order.STATUS_PAID:
        logger.warning(
            "order_update_rejected_direct_paid_transition",
            order_id=str(order.public_id),
            old_status=old_status,
            new_status=new_status,
        )
        raise ValidationError({"status": ["Direct order payment is blocked. Use payment capture endpoint."]})

    if new_status == Order.STATUS_CANCELLED:
        if old_status == Order.STATUS_DRAFT:
            serializer.instance = cancel_draft_order(order=order, actor=actor)
            return

        serializer.instance = cancel_order(order=order, actor=actor)
        return

    serializer.save()
