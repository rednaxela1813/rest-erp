from __future__ import annotations

from decimal import Decimal

from django.conf import settings

from apps.payments.models import CashierSession
from apps.products.models import Product

from .cart import (
    SESSION_CART,
    build_cart_context,
    get_cart,
    reset_checkout_idempotency,
    restore_cart_from_payload,
)
from .order_builder import product_checkout_error


def add_product_to_cart(*, request_session, session: CashierSession, product: Product) -> dict:
    cart = get_cart(request_session)
    error = ""
    if not product.unit or not product.tax_rate:
        error = product_checkout_error(product)
    else:
        _increment_cart_item(cart=cart, product=product)
        reset_checkout_idempotency(request_session)
        request_session.modified = True

    return build_cart_context(cart, session.org, last_added=product, cart_error=error)


def add_barcode_to_cart(*, request_session, session: CashierSession, barcode: str) -> dict:
    product = Product.objects.filter(org=session.org, barcode=barcode).first()
    cart = get_cart(request_session)
    error = ""

    if not barcode:
        error = "Barcode is required."
    elif not product:
        error = f"Product with barcode {barcode} not found."
    elif not product.unit or not product.tax_rate:
        error = product_checkout_error(product)
    else:
        _increment_cart_item(cart=cart, product=product)
        reset_checkout_idempotency(request_session)
        request_session.modified = True

    return build_cart_context(cart, session.org, cart_error=error)


def remove_product_from_cart(*, request_session, session: CashierSession, product: Product) -> dict:
    cart = get_cart(request_session)
    key = str(product.id)
    if key in cart:
        new_qty = cart[key] - 1
        if new_qty <= 0:
            cart.pop(key, None)
        else:
            cart[key] = new_qty
        reset_checkout_idempotency(request_session)
        request_session.modified = True

    return build_cart_context(cart, session.org)


def clear_cart(*, request_session, session: CashierSession) -> dict:
    cart = get_cart(request_session)
    cart.clear()
    reset_checkout_idempotency(request_session)
    request_session.modified = True

    return {
        "org": session.org,
        "cart_items": [],
        "cart_count": 0,
        "totals": {"subtotal": Decimal("0.00"), "total": Decimal("0.00")},
        "currency": _default_currency(),
    }


def restore_cart(*, request_session, session: CashierSession, raw_items: str) -> dict:
    cart = restore_cart_from_payload(raw_items, session.org)
    request_session[SESSION_CART] = cart
    reset_checkout_idempotency(request_session)
    request_session.modified = True
    return build_cart_context(cart, session.org, cart_error="")


def _increment_cart_item(*, cart: dict[str, int], product: Product) -> None:
    key = str(product.id)
    cart[key] = cart.get(key, 0) + 1


def _default_currency() -> str:
    return settings.DEFAULT_CURRENCY
