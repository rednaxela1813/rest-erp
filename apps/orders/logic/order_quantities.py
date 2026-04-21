from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from apps.products.models import Product


def aggregate_order_quantities(items: Iterable) -> tuple[dict[int, Decimal], dict[int, Decimal]]:
    qty_by_product_id: dict[int, Decimal] = {}
    kitchen_qty_by_product_id: dict[int, Decimal] = {}

    for item in items:
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
                target = kitchen_qty_by_product_id if component.requires_preparation else qty_by_product_id
                target[component.id] = target.get(component.id, Decimal("0")) + component_qty
            continue

        if product.product_type == Product.PRODUCT_TYPE_PREPARED:
            kitchen_qty_by_product_id[product.id] = kitchen_qty_by_product_id.get(product.id, Decimal("0")) + item_qty
            recipe = getattr(product, "recipe", None)
            if recipe:
                for ingredient in recipe.ingredients.all():
                    ingredient_product = ingredient.product
                    if not ingredient_product:
                        continue

                    ingredient_qty = item_qty * ingredient.quantity
                    qty_by_product_id[ingredient_product.id] = (
                        qty_by_product_id.get(ingredient_product.id, Decimal("0")) + ingredient_qty
                    )
            continue

        if product.requires_preparation:
            kitchen_qty_by_product_id[product.id] = kitchen_qty_by_product_id.get(product.id, Decimal("0")) + item_qty
        else:
            qty_by_product_id[product.id] = qty_by_product_id.get(product.id, Decimal("0")) + item_qty

    return qty_by_product_id, kitchen_qty_by_product_id
