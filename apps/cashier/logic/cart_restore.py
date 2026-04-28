from __future__ import annotations

import json

from apps.products.models import Product
from config.orgs.models import Organization


def restore_cart_from_payload(raw: str, org: Organization) -> dict[str, int]:
    """
    Восстанавливает корзину из JSON-строки [{id, qty}, ...].
    Валидирует каждый продукт (существование, unit, tax_rate).
    """
    try:
        items_data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        items_data = []

    cart: dict[str, int] = {}
    for entry in items_data:
        try:
            product_id = int(entry.get("id", 0))
            qty = max(1, int(entry.get("qty", 1)))
        except (TypeError, ValueError):
            continue

        try:
            product = Product.objects.get(id=product_id, org=org)
        except Product.DoesNotExist:
            continue

        if not product.unit or not product.tax_rate:
            continue

        cart[str(product_id)] = cart.get(str(product_id), 0) + qty

    return cart
