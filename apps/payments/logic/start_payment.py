from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import ValidationError
import structlog

from apps.payments.models import OrderPayment

logger = structlog.get_logger(__name__)


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
    logger.info(
        "payment_start_requested",
        order_id=str(order.public_id),
        tender=tender,
        amount=str(amount),
        currency=currency,
        provider=provider,
        idempotency_key=idempotency_key or "",
    )
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
                    logger.warning(
                        "payment_start_idempotency_conflict",
                        order_id=str(order.public_id),
                        existing_payment_id=str(existing.public_id),
                        idempotency_key=idempotency_key,
                    )
                    raise ValidationError(
                        {"idempotency_key": ["Idempotency key already used."]}
                    )
                logger.info(
                    "payment_start_reused_existing",
                    order_id=str(order.public_id),
                    payment_id=str(existing.public_id),
                    idempotency_key=idempotency_key,
                )
                return existing

        payment = OrderPayment.objects.create(
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
        logger.info(
            "payment_start_created",
            order_id=str(order.public_id),
            payment_id=str(payment.public_id),
            idempotency_key=idempotency_key or "",
        )
        return payment
