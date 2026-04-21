"""
Cart and session-state helpers.

Всё что касается корзины и сессионного состояния кассира:
- чтение/запись корзины в Django session
- сборка cart_items из product ids
- подсчёт totals
- фильтрация продуктов для каталога
"""

from __future__ import annotations

import json
from decimal import Decimal

from django.db.models import Q, Sum

from apps.products.models import Product
from apps.recipes.services.check_ingredients import has_enough_ingredients
from config.orgs.models import Organization

SESSION_ORG_ID = "cashier_org_id"
SESSION_SESSION_ID = "cashier_session_id"
SESSION_CART = "cashier_cart"
SESSION_CHECKOUT_IDEMPOTENCY = "cashier_checkout_idempotency"
SESSION_CHECKOUT_ERROR = "cashier_checkout_error"
SESSION_REFUND_ERROR = "cashier_refund_error"


# ── Cart session helpers ─────────────────────────────────────────────────────


def get_cart(session) -> dict[str, int]:
    cart = session.get(SESSION_CART)
    if not isinstance(cart, dict):
        cart = {}
        session[SESSION_CART] = cart
    return cart


def reset_checkout_idempotency(session) -> None:
    session.pop(SESSION_CHECKOUT_IDEMPOTENCY, None)


def cart_fingerprint(*, cart: dict[str, int], tender: str) -> str:
    if not cart:
        return ""
    items = [f"{product_id}:{qty}" for product_id, qty in sorted(cart.items())]
    return f"{tender}|" + "|".join(items)


# ── Product catalog ──────────────────────────────────────────────────────────


def get_products(org: Organization | None, query: str = "") -> list[Product]:
    """
    Возвращает продукты доступные для продажи:
    - только активные, с unit и tax_rate, не ингредиенты
    - для PREPARED: проверяем наличие ингредиентов через has_enough_ingredients
    - для остальных: проверяем stock_qty > 0
    """
    if not org:
        return Product.objects.none()

    qs = (
        Product.objects.filter(
            org=org,
            status=Product.STATUS_ACTIVE,
            unit__isnull=False,
            tax_rate__isnull=False,
        )
        .exclude(product_type=Product.PRODUCT_TYPE_INGREDIENT)
        .annotate(
            stock_qty_annotated=Sum(
                "stock_lots__remaining_qty",
                filter=Q(stock_lots__status="active"),
            )
        )
        .prefetch_related("recipe__ingredients__product__stock_lots")
        .order_by("name")
    )
    if query:
        qs = qs.filter(name__icontains=query)

    result = []
    for product in qs:
        if product.product_type == Product.PRODUCT_TYPE_PREPARED:
            if has_enough_ingredients(product):
                result.append(product)
        else:
            stock_qty = product.stock_qty_annotated or Decimal("0.000")
            if stock_qty > 0:
                result.append(product)
    return result


# ── Cart items and totals ────────────────────────────────────────────────────


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
    from django.conf import settings

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
