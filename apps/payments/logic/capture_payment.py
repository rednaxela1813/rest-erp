# apps/payments/logic/capture_payment.py
from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.payments.models import OrderPayment, PaymentEvent


def capture_payment(*, payment: OrderPayment, actor=None, metadata: dict | None = None) -> OrderPayment:
    """
    Use-case: CAPTURE платежа.

    Зачем row-lock:
    - POS/эквайринг/ретраи могут прислать повторный capture параллельно.
    - Мы обязаны сериализовать изменение статуса, чтобы:
        * не было двойных переходов
        * аудит (PaymentEvent) был корректным и однозначным.

    Строгое правило:
    - captured -> captured запрещаем (400), не делаем “тихий” idempotent success.
    """

    if metadata is None:
        metadata = {}

    with transaction.atomic():
        # lock payment row (актуальное состояние)
        locked = (
            OrderPayment.objects.select_for_update()
            .select_related("org", "order")
            .get(pk=payment.pk)
        )

        if locked.status == OrderPayment.Status.CAPTURED:
            raise ValidationError({"status": ["Payment is already captured."]})

        # MVP: разрешаем только pending/authorized -> captured
        if locked.status not in {OrderPayment.Status.PENDING, OrderPayment.Status.AUTHORIZED}:
            raise ValidationError({"status": ["Invalid status transition."]})

        old_status = locked.status

        locked.status = OrderPayment.Status.CAPTURED

        # Инвариант модели: статус можно менять только через use-case
        locked._status_change_allowed = True
        locked.save(update_fields=["status", "updated_at"])

        PaymentEvent.objects.create(
            org=locked.org,
            payment=locked,
            actor=actor if actor is not None else None,
            terminal=None,
            from_status=old_status,
            to_status=OrderPayment.Status.CAPTURED,
            action="capture",
            metadata=metadata,
        )

        return locked
