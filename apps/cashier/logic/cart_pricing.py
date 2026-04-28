from __future__ import annotations

from decimal import Decimal

from django.conf import settings

from apps.products.models import Product
from config.orgs.models import Organization


def get_product_unit_price(product: Product) -> Decimal:
    if product.is_bundle:
        return product.recompute_bundle_price()
    return product.unit_price


def tax_included_amount(amount: Decimal, rate: Decimal) -> Decimal:
    if rate <= 0:
        return Decimal("0.00")
    divisor = Decimal("1.00") + (rate / Decimal("100"))
    if divisor == 0:
        return Decimal("0.00")
    return (amount - (amount / divisor)).quantize(Decimal("0.01"))


def cart_items(cart: dict[str, int], org: Organization | None) -> list[dict]:
    if not cart or not org:
        return []

    product_ids = [int(pid) for pid in cart.keys() if pid.isdigit()]
    products_by_id = {
        str(product.id): product
        for product in Product.objects.filter(org=org, id__in=product_ids).prefetch_related("bundle_items__component")
    }

    items: list[dict] = []
    for product_id, qty in cart.items():
        product = products_by_id.get(product_id)
        if not product:
            continue
        unit_price = get_product_unit_price(product)
        line_total = (unit_price * Decimal(qty)).quantize(Decimal("0.01"))
        tax_rate = product.tax_rate.rate if product.tax_rate else Decimal("0.00")
        tax_amount = tax_included_amount(line_total, tax_rate)
        items.append(
            {
                "product": product,
                "qty": qty,
                "line_total": line_total,
                "unit_price": unit_price,
                "tax_amount": tax_amount,
            }
        )
    return items


def cart_totals(items: list[dict]) -> dict:
    subtotal = sum((item["line_total"] for item in items), Decimal("0.00"))
    tax_total = sum((item["tax_amount"] for item in items), Decimal("0.00"))
    return {
        "subtotal": subtotal.quantize(Decimal("0.01")),
        "total": subtotal.quantize(Decimal("0.01")),
        "tax_total": tax_total.quantize(Decimal("0.01")),
    }


def build_cart_context(cart: dict[str, int], org: Organization, **extra) -> dict:
    """Собирает стандартный контекст для cart-партиалов."""
    items = cart_items(cart, org)
    totals = cart_totals(items)
    return {
        "org": org,
        "cart_items": items,
        "cart_count": sum(cart.values()) if cart else 0,
        "totals": totals,
        "currency": settings.DEFAULT_CURRENCY,
        **extra,
    }
