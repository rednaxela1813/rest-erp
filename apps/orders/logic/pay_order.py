from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.orders.logic.status_fsm import assert_can_transition
from apps.orders.models import Order


def pay_order(*, order: Order, actor=None) -> Order:
    """
    Use-case: оплатить заказ (draft -> paid) с проверкой и списанием склада.

    Инварианты:
    - Double-pay запрещён (paid -> paid должен вернуть 400).
    - Оплата возможна только из draft.
    - Stock проверяем и списываем АГРЕГИРОВАННО по Product (POS-инвариант).
    - В случае ошибки: никаких изменений (transaction.atomic).
    - Для конкурентной безопасности:
        * row-lock на Order (select_for_update)
        * row-lock на Product (select_for_update)
    - Пишем историю статусов (OrderStatusEvent)
    """

    # Быстрая проверка (может быть stale, но отсекает очевидные кейсы)
    assert_can_transition(current=order.status, new=Order.STATUS_PAID)

    if order.status == Order.STATUS_PAID:
        raise ValidationError({"status": ["Order is already paid."]})
    if order.status != Order.STATUS_DRAFT:
        raise ValidationError({"status": ["Invalid status transition."]})

    with transaction.atomic():
        # lock order row + актуальное состояние
        order = Order.objects.select_for_update().get(pk=order.pk)

        # повторная проверка под lock
        assert_can_transition(current=order.status, new=Order.STATUS_PAID)

        if order.status == Order.STATUS_PAID:
            raise ValidationError({"status": ["Order is already paid."]})
        if order.status != Order.STATUS_DRAFT:
            raise ValidationError({"status": ["Invalid status transition."]})

        items_qs = order.items.select_related("product").all()
        if not items_qs.exists():
            raise ValidationError({"order": "Cannot pay order without items."})

        # агрегируем qty
        qty_by_product_id: dict[int, Decimal] = {}
        for item in items_qs:
            pid = item.product_id
            item_qty = item.qty if isinstance(item.qty, Decimal) else Decimal(str(item.qty))
            qty_by_product_id[pid] = qty_by_product_id.get(pid, Decimal("0")) + item_qty

        # lock products
        from apps.products.models import Product

        locked_products = Product.objects.select_for_update().filter(
            id__in=list(qty_by_product_id.keys())
        )
        products_map = {p.id: p for p in locked_products}

        # check stock
        for pid, total_qty in qty_by_product_id.items():
            p = products_map[pid]
            if p.stock_qty < total_qty:
                raise ValidationError({"order": "Insufficient stock."})

        # write-off stock
        for pid, total_qty in qty_by_product_id.items():
            p = products_map[pid]
            p.stock_qty = p.stock_qty - total_qty

            fields = ["stock_qty"]
            if "updated_at" in [f.name for f in p._meta.fields]:
                fields.append("updated_at")
            p.save(update_fields=fields)

        # status change + history event
        old_status = order.status
        order.status = Order.STATUS_PAID
        order.save(update_fields=["status", "updated_at"])

        from apps.orders.models import OrderStatusEvent

        from apps.orders.models import OrderStatusEvent

        OrderStatusEvent.objects.create(
            org=order.org,
            order=order,
            from_status=old_status,
            to_status=Order.STATUS_PAID,
            actor=actor if actor is not None else None,
        )


    return order
