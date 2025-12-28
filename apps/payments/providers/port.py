# apps/payments/providers/port.py
from __future__ import annotations

from typing import Protocol, Any
from apps.payments.models import OrderPayment


class PaymentProviderPort(Protocol):
    """
    Порт (интерфейс) для эквайринга/фискального ПО.

    Пока минимально. Дальше добавим:
    - capture/refund/void
    - check_status
    - retries/backoff/timeouts
    """

    def authorize(self, *, payment: OrderPayment, timeout_s: int) -> dict[str, Any]:
        ...
