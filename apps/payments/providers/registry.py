# apps/payments/providers/registry.py
from __future__ import annotations

from apps.payments.models import OrderPayment
from apps.payments.providers.manual import ManualProvider


def get_provider_for_payment(payment: OrderPayment):
    """
    MVP-registry: выбираем провайдера по payment.provider.

    Позже:
    - внедрим DI (container) или настройку org->provider
    - добавим caching, healthchecks
    """
    if payment.provider == "manual":
        return ManualProvider()

    # Без сюрпризов: если провайдер неизвестен — явно падаем
    raise ValueError(f"Unknown payment provider: {payment.provider}")
