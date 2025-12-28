# apps/payments/logic/authorize_payment.py
from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.payments.models import OrderPayment, PaymentEvent
from apps.payments.providers import registry


def authorize_payment(
    *,
    payment: OrderPayment,
    actor=None,
    metadata: dict | None = None,
    timeout_s: int = 10,
) -> OrderPayment:
    """
    Use-case: AUTHORIZE платежа (pending -> authorized).

    Конкурентность:
    - POS/эквайринг часто ретраят запросы / двойные клики возможны.
    - Два параллельных authorize не должны “тихо” пройти.
      Поэтому: transaction.atomic + select_for_update на строку payment.

    Строго:
    - authorized -> authorized запрещаем (400).
    """

    if metadata is None:
        metadata = {}

    with transaction.atomic():
        locked = (
            OrderPayment.objects.select_for_update()
            .select_related("org", "order")
            .get(pk=payment.pk)
        )

        if locked.status == OrderPayment.Status.AUTHORIZED:
            raise ValidationError({"status": ["Payment is already authorized."]})

        if locked.status != OrderPayment.Status.PENDING:
            raise ValidationError({"status": ["Invalid status transition."]})

        old_status = locked.status

        # ВАЖНО: вызываем через registry, чтобы monkeypatch работал по пути
        provider = registry.get_provider_for_payment(locked)
        payload = provider.authorize(payment=locked, timeout_s=timeout_s)

        locked.raw_provider_payload = payload
        locked.status = OrderPayment.Status.AUTHORIZED
        locked._status_change_allowed = True
        locked.save(update_fields=["raw_provider_payload", "status", "updated_at"])

        PaymentEvent.objects.create(
            org=locked.org,
            payment=locked,
            actor=actor if actor is not None else None,
            terminal=None,
            from_status=old_status,
            to_status=OrderPayment.Status.AUTHORIZED,
            action="authorize",
            metadata=metadata,
        )

        return locked
