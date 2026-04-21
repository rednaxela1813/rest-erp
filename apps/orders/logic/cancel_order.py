from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import ValidationError
import structlog

from apps.orders.logic.order_quantities import aggregate_order_quantities
from apps.orders.models import Order
from apps.orders.signals import order_cancelled

logger = structlog.get_logger(__name__)


def cancel_order(*, order: Order, actor=None) -> Order:
    """
    Use-case: отмена ОПЛАЧЕННОГО заказа (paid -> cancelled) + возврат склада.

    Инварианты:
    - отменять можно только paid
    - повторная отмена запрещена
    - возврат склада атомарен (transaction.atomic)
    - row-lock на Order (select_for_update)
    - row-lock на Product (select_for_update)
    - qty агрегируем по product_id (как в pay_order)
    - Пишем историю статусов (OrderStatusEvent)

    ВАЖНО:
    - входной `order` может быть stale (не обновлён из БД),
      поэтому статус проверяем ТОЛЬКО после row-lock внутри atomic.
    """

    with transaction.atomic():
        locked_order = Order.objects.select_for_update().get(pk=order.pk)

        if locked_order.status == Order.STATUS_CANCELLED:
            raise ValidationError({"status": ["Order is already cancelled."]})
        if locked_order.status != Order.STATUS_PAID:
            raise ValidationError({"status": ["Only paid orders can be cancelled."]})

        items_qs = locked_order.items.select_related("product").prefetch_related(
            "product__bundle_items__component",
            "product__recipe__ingredients__product",
        )
        if not items_qs.exists():
            raise ValidationError({"order": "Cannot cancel order without items."})

        _, kitchen_qty_by_product_id = aggregate_order_quantities(items_qs)

        order_cancelled.send(
            sender=Order,
            order=locked_order,
            items=items_qs,
            user=actor,
        )

        old_status = locked_order.status
        locked_order.status = Order.STATUS_CANCELLED
        locked_order.save(update_fields=["status", "updated_at"])

        from apps.orders.models import KitchenTicket, OrderStatusEvent

        if kitchen_qty_by_product_id:
            KitchenTicket.objects.filter(
                order=locked_order,
                status__in=[KitchenTicket.Status.PENDING, KitchenTicket.Status.IN_PROGRESS],
            ).update(status=KitchenTicket.Status.CANCELLED)

        OrderStatusEvent.objects.create(
            org=locked_order.org,
            order=locked_order,
            from_status=old_status,
            to_status=Order.STATUS_CANCELLED,
            actor=actor if actor is not None else None,
        )

        logger.info(
            "order_cancelled",
            order_id=str(locked_order.public_id),
            actor_id=str(actor.id) if actor else "",
        )

        return locked_order
