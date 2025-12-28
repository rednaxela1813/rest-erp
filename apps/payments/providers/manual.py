# apps/payments/providers/manual.py
from __future__ import annotations

from typing import Any
from apps.payments.models import OrderPayment


class ManualProvider:
    """
    Заглушка для ручных платежей / development.

    В реальности тут может быть:
    - "cash"
    - "manual card"
    - "prepaid external"
    """

    def authorize(self, *, payment: OrderPayment, timeout_s: int) -> dict[str, Any]:
        return {"ok": True, "provider": "manual", "note": "authorized manually"}

