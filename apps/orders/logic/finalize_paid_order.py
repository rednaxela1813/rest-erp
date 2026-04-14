from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError
import structlog

from apps.orders.logic.status_fsm import assert_can_transition
from apps.orders.models import Order

from apps.accounting.logic.record_stock_out import record_stock_out

from apps.products.models import Product

logger = structlog.get_logger(__name__)


def finalize_paid_order(*, order: Order, actor=None) -> Order:
    """
    Use-case: finalize payment by moving order to paid and writing off stock.
    """
    logger.info(
        "order_finalize_started",
        order_id=str(order.public_id),
        actor_id=str(actor.id) if actor else "",
        current_status=order.status,
    )
    assert_can_transition(current=order.status, new=Order.STATUS_PAID)

    if order.status == Order.STATUS_PAID:
        raise ValidationError({"status": ["Order is already paid."]})
    if order.status != Order.STATUS_DRAFT:
        raise ValidationError({"status": ["Invalid status transition."]})

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)

        assert_can_transition(current=order.status, new=Order.STATUS_PAID)

        if order.status == Order.STATUS_PAID:
            raise ValidationError({"status": ["Order is already paid."]})
        if order.status != Order.STATUS_DRAFT:
            raise ValidationError({"status": ["Invalid status transition."]})

        items_qs = order.items.select_related("product").prefetch_related(
            "product__bundle_items__component", "product__recipe__ingredients__product"
        )
        if not items_qs.exists():
            raise ValidationError({"order": "Cannot pay order without items."})
        
         


        qty_by_product_id: dict[int, Decimal] = {}
        kitchen_qty_by_product_id: dict[int, Decimal] = {}
        for item in items_qs:
            if not item.product_id:
                continue
            item_qty = item.qty if isinstance(item.qty, Decimal) else Decimal(str(item.qty))
            product = item.product
            if product and product.is_bundle:
                for bundle_item in product.bundle_items.all():
                    component = bundle_item.component
                    if not component:
                        continue
                    component_qty = item_qty * bundle_item.qty
                    if component.requires_preparation:
                        kitchen_qty_by_product_id[component.id] = kitchen_qty_by_product_id.get(
                            component.id, Decimal("0")
                        ) + component_qty
                    else:
                        qty_by_product_id[component.id] = qty_by_product_id.get(
                            component.id, Decimal("0")
                        ) + component_qty
            elif product.product_type == Product.PRODUCT_TYPE_PREPARED:
                # The prepared product itself (e.g. burger) goes to the kitchen.
                kitchen_qty_by_product_id[product.id] = kitchen_qty_by_product_id.get(
                    product.id, Decimal("0")
                ) + item_qty
                # Its ingredients are deducted from stock.
                recipe = getattr(product, "recipe", None)
                if recipe:
                    for ingredient in recipe.ingredients.all():
                        ingredient_product = ingredient.product
                        if not ingredient_product:
                            continue
                        ingredient_qty = item_qty * ingredient.quantity
                        qty_by_product_id[ingredient_product.id] = qty_by_product_id.get(
                            ingredient_product.id, Decimal("0")
                        ) + ingredient_qty
            else:
                if product.requires_preparation:
                    kitchen_qty_by_product_id[product.id] = kitchen_qty_by_product_id.get(
                        product.id, Decimal("0")
                    ) + item_qty
                else:
                    qty_by_product_id[product.id] = qty_by_product_id.get(
                        product.id, Decimal("0")
                    ) + item_qty

        

        locked_products = Product.objects.select_for_update().filter(
            id__in=list(qty_by_product_id.keys())
        )
        products_map = {p.id: p for p in locked_products}

        from apps.inventory.exceptions import InsufficientStock
        from apps.inventory.services.deduct_stock import deduct_stock

        for pid, total_qty in qty_by_product_id.items():
            p = products_map[pid]
            try:
                movements = deduct_stock(
                    org=order.org,
                    product=p,
                    quantity=total_qty,
                    reason="order_paid",
                    comment=str(order.public_id),
                )
                # for m in movements:                

                #     record_stock_out(movement=m)  # связать с функцией, которая создаёт запись в бухгалтерии
                    
            except InsufficientStock as e:
                logger.warning(
                    "order_finalize_insufficient_stock",
                    order_id=str(order.public_id),
                    product_id=str(p.public_id),
                    product_name=p.name,
                    requested_qty=str(total_qty),
                    error=str(e),
                )
                raise ValidationError({"order": str(e)})

        old_status = order.status
        order.status = Order.STATUS_PAID
        order.save(update_fields=["status", "updated_at"])

        from apps.orders.models import KitchenTicket, OrderStatusEvent

        if kitchen_qty_by_product_id:
            KitchenTicket.objects.bulk_create(
                [
                    KitchenTicket(
                        org=order.org,
                        order=order,
                        product_id=pid,
                        qty=qty,
                    )
                    for pid, qty in kitchen_qty_by_product_id.items()
                ]
            )

        OrderStatusEvent.objects.create(
            org=order.org,
            order=order,
            from_status=old_status,
            to_status=Order.STATUS_PAID,
            actor=actor if actor is not None else None,
        )

    logger.info(
        "order_finalize_succeeded",
        order_id=str(order.public_id),
        actor_id=str(actor.id) if actor else "",
        inventory_products_count=len(qty_by_product_id),
        kitchen_products_count=len(kitchen_qty_by_product_id),
        kitchen_ticket_count=len(kitchen_qty_by_product_id),
    )
    return order
