from __future__ import annotations

from django.conf import settings

from apps.payments.models import CashierSession, OrderPayment


def create_payment(
    *,
    order,
    session: CashierSession,
    tender: str,
    idempotency_key: str | None = None,
) -> OrderPayment:
    """Создаёт OrderPayment в статусе PENDING."""
    return OrderPayment.objects.create(
        org=order.org,
        order=order,
        terminal=session.terminal,
        tender=tender,
        status=OrderPayment.Status.PENDING,
        amount=order.total,
        currency=settings.DEFAULT_CURRENCY,
        provider="manual",
        idempotency_key=idempotency_key,
    )
