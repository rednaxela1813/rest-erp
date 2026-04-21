"""
Order creation from cashier cart.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.orders.models import Order, OrderItem
from apps.products.models import Product
from config.orgs.models import Organization

from .cart import get_product_unit_price


def build_order_from_cart(*, org: Organization, cart_items: list[dict]) -> Order:
    """
    Создаёт Order и OrderItem'ы из cart_items.
    Бросает ValueError если корзина пустая или у продукта нет unit/tax_rate.
    Всё в одной транзакции — не будет «висячих» черновиков.
    """
    if not cart_items:
        raise ValueError("Cart is empty.")

    for item in cart_items:
        product: Product = item["product"]
        if not product.unit or not product.tax_rate:
            raise ValueError("Product is missing unit or tax rate.")

    with transaction.atomic():
        order = Order.objects.create(org=org)
        for item in cart_items:
            product: Product = item["product"]
            unit_price = item.get("unit_price") or get_product_unit_price(product)
            OrderItem.objects.create(
                order=order,
                product=product,
                product_name=product.name,
                qty=Decimal(item["qty"]),
                unit=product.unit,
                unit_price=unit_price,
                tax_rate=product.tax_rate,
            )
        order.recompute_totals()
        order.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])
    return order


def product_checkout_error(product: Product) -> str:
    return f'Product "{product.name}" cannot be sold in cashier until unit and tax rate are set.'
