from __future__ import annotations

from apps.orders.logic.finalize_paid_order import finalize_paid_order
from apps.orders.models import Order


def pay_order(*, order: Order, actor=None) -> Order:
    """
    Backwards-compatible wrapper. Real payment capture should call finalize_paid_order.
    """
    return finalize_paid_order(order=order, actor=actor)
