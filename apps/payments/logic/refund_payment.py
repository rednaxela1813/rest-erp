# apps/payments/logic/refund_payment.py
from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.payments.models import OrderPayment, PaymentEvent


def refund_payment(*, payment: OrderPayment, actor=None, metadata: dict | None = None) -> OrderPayment:
    """
    Use-case: REFUND платежа.

    Смысл:
    - Возврат денег после фактического списания (captured -> refunded).
    - Это НЕ void. Void — до списания.

    Конкурентность:
    - ретраи/двойные webhook'и => row-lock обязателен.

    Строго:
    - refunded -> refunded запрещаем (400), чтобы не было "тихих" дублей.
    """

    if metadata is None:
        metadata = {}

    with transaction.atomic():
        locked = (
            OrderPayment.objects.select_for_update()
            .select_related("org", "order")
            .get(pk=payment.pk)
        )

        if locked.status == OrderPayment.Status.REFUNDED:
            raise ValidationError({"status": ["Payment is already refunded."]})

        if locked.status != OrderPayment.Status.CAPTURED:
            raise ValidationError({"status": ["Invalid status transition."]})

        old_status = locked.status

        locked.status = OrderPayment.Status.REFUNDED
        locked._status_change_allowed = True
        locked.save(update_fields=["status", "updated_at"])

        PaymentEvent.objects.create(
            org=locked.org,
            payment=locked,
            actor=actor if actor is not None else None,
            terminal=None,
            from_status=old_status,
            to_status=OrderPayment.Status.REFUNDED,
            action="refund",
            metadata=metadata,
        )

        return locked
