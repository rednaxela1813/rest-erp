from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.payments.models import OrderPayment


def start_payment(
    *,
    order,
    tender: str,
    amount,
    currency: str,
    provider: str = "manual",
    terminal=None,
    idempotency_key: str | None = None,
) -> OrderPayment:
    """
    Use-case: create (or reuse) a payment intent for an order.
    Idempotency: same key returns the same payment if parameters match.
    """
    with transaction.atomic():
        if idempotency_key:
            existing = OrderPayment.objects.filter(
                org=order.org, idempotency_key=idempotency_key
            ).select_for_update().first()
            if existing:
                if (
                    existing.order_id != order.id
                    or existing.amount != amount
                    or existing.tender != tender
                    or existing.currency != currency
                ):
                    raise ValidationError(
                        {"idempotency_key": ["Idempotency key already used."]}
                    )
                return existing

        return OrderPayment.objects.create(
            org=order.org,
            order=order,
            terminal=terminal,
            tender=tender,
            status=OrderPayment.Status.PENDING,
            amount=amount,
            currency=currency,
            provider=provider,
            idempotency_key=idempotency_key,
        )
