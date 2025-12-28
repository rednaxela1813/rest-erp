#apps/orders/logic/status_fsm.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from rest_framework.exceptions import ValidationError

from apps.orders.models import Order


@dataclass(frozen=True)
class TransitionResult:
    ok: bool
    reason: str | None = None


# Один источник правды: allowed transitions
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Order.STATUS_DRAFT: {Order.STATUS_PAID, Order.STATUS_CANCELLED},
    Order.STATUS_PAID: {Order.STATUS_CANCELLED},
    Order.STATUS_CANCELLED: set(),
}


def can_transition(*, current: str, new: str) -> TransitionResult:
    if new == current:
        return TransitionResult(ok=True)

    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new in allowed:
        return TransitionResult(ok=True)

    return TransitionResult(ok=False, reason="Invalid status transition.")


def assert_can_transition(*, current: str, new: str) -> None:
    """
    Бросает DRF ValidationError если переход запрещён.
    Используем и в API, и в use-case'ах, чтобы контракт был единым.
    """
    res = can_transition(current=current, new=new)
    if not res.ok:
        raise ValidationError({"status": [res.reason or "Invalid status transition."]})


def allowed_next_statuses(*, current: str) -> Iterable[str]:
    return sorted(ALLOWED_TRANSITIONS.get(current, set()))
