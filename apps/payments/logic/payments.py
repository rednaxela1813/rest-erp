from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db import transaction

from apps.payments.models import OrderPayment, PaymentEvent
from django.core.exceptions import ValidationError



@transaction.atomic
def create_payment(
    *,
    order,
    tender: str,
    amount: Decimal,
    currency: str,
    actor=None,
    idempotency_key: str | None = None,
    external_id: str | None = None,
    provider: str = "manual",
    metadata: dict[str, Any] | None = None,
) -> OrderPayment:
    """
    Создаёт платёж в статусе pending + одно событие PaymentEvent(action='create').

    Инварианты MVP:
    - org-scope обязателен: платёж всегда создаётся внутри order.org.
    - идемпотентность:
      если idempotency_key задан и уже существует платёж (org + key) -> вернуть его
      и НЕ создавать дубликаты PaymentEvent.
    - транзакция atomic нужна, потому что:
      1) в следующих шагах мы будем делать цепочки authorize/capture/refund и они должны быть согласованы,
      2) дедупликация должна быть “надёжной” на ретраях.
    """
    org = order.org
    metadata = metadata or {}

    if idempotency_key:
        existing = (
            OrderPayment.objects
            .filter(org=org, idempotency_key=idempotency_key)
            .select_for_update()  # защищаемся от гонки при параллельных ретраях
            .first()
        )
        if existing:
            return existing

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=tender,
        status=OrderPayment.Status.PENDING,
        amount=amount,
        currency=currency,
        idempotency_key=idempotency_key,
        external_id=external_id,
        provider=provider,
    )

    PaymentEvent.objects.create(
        org=org,
        payment=payment,
        actor=actor,
        terminal=None,
        from_status=None,
        to_status=payment.status,
        action="create",
        metadata=metadata,
    )

    return payment





@transaction.atomic
def authorize_payment(*, payment: OrderPayment, actor=None, metadata: dict | None = None) -> OrderPayment:
    """
    Переход pending -> authorized.

    Важно:
    - row-lock по payment, чтобы два параллельных authorize не прошли оба.
    - статус меняем только через allow-флаг, иначе модельный инвариант заблокирует save().
    - создаём PaymentEvent на каждый переход.
    """
    metadata = metadata or {}

    locked = (
        OrderPayment.objects
        .select_for_update()
        .select_related("org")
        .get(pk=payment.pk)
    )

    if locked.status != OrderPayment.Status.PENDING:
        raise ValidationError("Only pending payments can be authorized")

    from_status = locked.status
    locked.status = OrderPayment.Status.AUTHORIZED
    locked._status_change_allowed = True
    locked.save(update_fields=["status", "updated_at"])

    PaymentEvent.objects.create(
        org=locked.org,
        payment=locked,
        actor=actor,
        terminal=None,
        from_status=from_status,
        to_status=locked.status,
        action="authorize",
        metadata=metadata,
    )

    return locked




@transaction.atomic
def capture_payment(*, payment: OrderPayment, actor=None, metadata: dict | None = None) -> OrderPayment:
    """
    Переход authorized -> captured.

    Инварианты:
    - atomic + select_for_update на payment предотвращают гонки (двойной capture).
    - status меняется только через allow-флаг.
    - обязательно создаём PaymentEvent.
    """
    metadata = metadata or {}

    locked = (
        OrderPayment.objects
        .select_for_update()
        .select_related("org")
        .get(pk=payment.pk)
    )

    if locked.status != OrderPayment.Status.AUTHORIZED:
        raise ValidationError("Only authorized payments can be captured")

    from_status = locked.status
    locked.status = OrderPayment.Status.CAPTURED
    locked._status_change_allowed = True
    locked.save(update_fields=["status", "updated_at"])

    PaymentEvent.objects.create(
        org=locked.org,
        payment=locked,
        actor=actor,
        terminal=None,
        from_status=from_status,
        to_status=locked.status,
        action="capture",
        metadata=metadata,
    )

    return locked
