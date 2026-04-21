from __future__ import annotations

from apps.inventory.services.deduct_stock import restore_stock
from apps.orders.logic.order_quantities import aggregate_order_quantities
from apps.products.models import Product


def handle_order_cancelled_restore_stock(*, order, items, **kwargs) -> None:
    qty_by_product_id, _ = aggregate_order_quantities(items)
    if not qty_by_product_id:
        return

    locked_products = Product.objects.select_for_update().filter(id__in=list(qty_by_product_id.keys()))
    products_map = {product.id: product for product in locked_products}

    restored_movements = []
    for product_id, total_qty in qty_by_product_id.items():
        restored_movements.append(
            restore_stock(
                org=order.org,
                product=products_map[product_id],
                quantity=total_qty,
                reason="order_cancelled",
                comment=str(order.public_id),
            )
        )

    order._restored_stock_movements = restored_movements
