from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.orders.models import Order


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

        items_qs = locked_order.items.select_related("product").all()
        if not items_qs.exists():
            raise ValidationError({"order": "Cannot cancel order without items."})

        qty_by_product_id: dict[int, Decimal] = {}
        for item in items_qs:
            pid = item.product_id
            item_qty = item.qty if isinstance(item.qty, Decimal) else Decimal(str(item.qty))
            qty_by_product_id[pid] = qty_by_product_id.get(pid, Decimal("0")) + item_qty

        from apps.products.models import Product

        locked_products = Product.objects.select_for_update().filter(
            id__in=list(qty_by_product_id.keys())
        )
        products_map = {p.id: p for p in locked_products}

        for pid, total_qty in qty_by_product_id.items():
            p = products_map[pid]
            p.stock_qty = p.stock_qty + total_qty

            fields = ["stock_qty"]
            if "updated_at" in [f.name for f in p._meta.fields]:
                fields.append("updated_at")
            p.save(update_fields=fields)

        old_status = locked_order.status
        
        locked_order.status = Order.STATUS_CANCELLED
        locked_order._status_change_allowed = True
        locked_order.save(update_fields=["status", "updated_at"])


        from apps.orders.models import OrderStatusEvent

        

        OrderStatusEvent.objects.create(
            org=locked_order.org,
            order=locked_order,
            from_status=old_status,
            to_status=Order.STATUS_CANCELLED,
            actor=actor if actor is not None else None,
     )


        return locked_order
