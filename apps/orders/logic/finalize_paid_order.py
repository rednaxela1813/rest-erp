from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError
import structlog

from apps.orders.logic.status_fsm import assert_can_transition
from apps.orders.logic.order_quantities import aggregate_order_quantities
from apps.orders.models import Order

logger = structlog.get_logger(__name__)


def _validate_transition(order: Order) -> None:
    assert_can_transition(current=order.status, new=Order.STATUS_PAID)

    if order.status == Order.STATUS_PAID:
        raise ValidationError({"status": ["Order is already paid."]})
    if order.status != Order.STATUS_DRAFT:
        raise ValidationError({"status": ["Invalid status transition."]})


def _aggregate_quantities(order: Order) -> tuple[dict[int, Decimal], dict[int, Decimal]]:
    items_qs = order.items.select_related("product").prefetch_related(
        "product__bundle_items__component", "product__recipe__ingredients__product"
    )
    if not items_qs.exists():
        raise ValidationError({"order": "Cannot pay order without items."})

    return aggregate_order_quantities(items_qs)


def _deduct_inventory(order: Order, qty_by_product_id: dict[int, Decimal]) -> None:
    from apps.products.models import Product

    locked_products = Product.objects.select_for_update().filter(id__in=list(qty_by_product_id.keys()))
    products_map = {product.id: product for product in locked_products}

    from apps.inventory.exceptions import InsufficientStock
    from apps.inventory.services.deduct_stock import deduct_stock

    for product_id, total_qty in qty_by_product_id.items():
        product = products_map[product_id]
        try:
            deduct_stock(
                org=order.org,
                product=product,
                quantity=total_qty,
                reason="order_paid",
                comment=str(order.public_id),
            )
        except InsufficientStock as exc:
            logger.warning(
                "order_finalize_insufficient_stock",
                order_id=str(order.public_id),
                product_id=str(product.public_id),
                product_name=product.name,
                requested_qty=str(total_qty),
                error=str(exc),
            )
            raise ValidationError({"order": str(exc)}) from exc


def _create_kitchen_tickets(order: Order, kitchen_qty_by_product_id: dict[int, Decimal]) -> None:
    if not kitchen_qty_by_product_id:
        return

    from apps.orders.models import KitchenTicket

    KitchenTicket.objects.bulk_create(
        [
            KitchenTicket(
                org=order.org,
                order=order,
                product_id=product_id,
                qty=qty,
            )
            for product_id, qty in kitchen_qty_by_product_id.items()
        ]
    )


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

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        _validate_transition(order)
        qty_by_product_id, kitchen_qty_by_product_id = _aggregate_quantities(order)
        _deduct_inventory(order, qty_by_product_id)

        old_status = order.status
        order.status = Order.STATUS_PAID
        order.save(update_fields=["status", "updated_at"])

        from apps.orders.models import OrderStatusEvent

        _create_kitchen_tickets(order, kitchen_qty_by_product_id)

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
