# apps/payments/logic/void_payment.py
from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.payments.models import OrderPayment, PaymentEvent


def void_payment(*, payment: OrderPayment, actor=None, metadata: dict | None = None) -> OrderPayment:
    """
    Use-case: VOID платежа.

    Смысл:
    - Отмена платежа до списания денег.
    - В реальном эквайринге void применяется к pending/authorized.

    Конкурентность:
    - ретраи POS/шлюза => row-lock обязателен.

    Строго:
    - voided -> voided запрещаем (400), никаких "тихих" успехов.
    """

    if metadata is None:
        metadata = {}

    with transaction.atomic():
        locked = (
            OrderPayment.objects.select_for_update()
            .select_related("org", "order")
            .get(pk=payment.pk)
        )

        if locked.status == OrderPayment.Status.VOIDED:
            raise ValidationError({"status": ["Payment is already voided."]})

        if locked.status not in {OrderPayment.Status.PENDING, OrderPayment.Status.AUTHORIZED}:
            raise ValidationError({"status": ["Invalid status transition."]})

        old_status = locked.status

        locked.status = OrderPayment.Status.VOIDED
        locked._status_change_allowed = True
        locked.save(update_fields=["status", "updated_at"])

        PaymentEvent.objects.create(
            org=locked.org,
            payment=locked,
            actor=actor if actor is not None else None,
            terminal=None,
            from_status=old_status,
            to_status=OrderPayment.Status.VOIDED,
            action="void",
            metadata=metadata,
        )

        return locked
