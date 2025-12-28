from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.orders.models import Order


def cancel_draft_order(*, order: Order, actor=None) -> Order:
    """
    Use-case: отменить черновик (draft -> cancelled) БЕЗ складских эффектов.

    Инварианты:
    - можно отменять только draft
    - повторная отмена запрещена
    - защищаемся от гонок: lock order row (select_for_update) внутри transaction.atomic
    - Пишем историю статусов (OrderStatusEvent)
    """

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)

        if order.status == Order.STATUS_CANCELLED:
            raise ValidationError({"status": ["Order is already cancelled."]})
        if order.status != Order.STATUS_DRAFT:
            raise ValidationError({"status": ["Only draft orders can be cancelled."]})

        old_status = order.status
        order.status = Order.STATUS_CANCELLED
        order.save(update_fields=["status", "updated_at"])

        from apps.orders.models import OrderStatusEvent

        

        OrderStatusEvent.objects.create(
            org=order.org,
            order=order,
            from_status=old_status,
            to_status=Order.STATUS_CANCELLED,
            actor=actor if actor is not None else None,
      )


    return order
