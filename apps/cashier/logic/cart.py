"""
Cart session-state facade.

Session keys and low-level session helpers live here. Product catalog,
pricing/totals and restore parsing are re-exported for compatibility with
existing imports.
"""

from __future__ import annotations

from .cart_pricing import (
    build_cart_context,
    cart_items,
    cart_totals,
    get_product_unit_price,
    tax_included_amount,
)
from .cart_restore import restore_cart_from_payload
from .product_catalog import get_products

SESSION_ORG_ID = "cashier_org_id"
SESSION_SESSION_ID = "cashier_session_id"
SESSION_CART = "cashier_cart"
SESSION_CHECKOUT_IDEMPOTENCY = "cashier_checkout_idempotency"
SESSION_CHECKOUT_ERROR = "cashier_checkout_error"
SESSION_REFUND_ERROR = "cashier_refund_error"


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


__all__ = [
    "SESSION_CART",
    "SESSION_CHECKOUT_ERROR",
    "SESSION_CHECKOUT_IDEMPOTENCY",
    "SESSION_ORG_ID",
    "SESSION_REFUND_ERROR",
    "SESSION_SESSION_ID",
    "build_cart_context",
    "cart_fingerprint",
    "cart_items",
    "cart_totals",
    "get_cart",
    "get_product_unit_price",
    "get_products",
    "reset_checkout_idempotency",
    "restore_cart_from_payload",
    "tax_included_amount",
]
