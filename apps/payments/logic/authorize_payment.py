from __future__ import annotations

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.payments.models import CashierSession, OrderPayment
from apps.payments.providers import registry


def authorize_payment(
    *,
    payment: OrderPayment,
    actor=None,
    terminal=None,
    session: CashierSession | None,
    timeout_s: int = 30,
) -> OrderPayment:
    if payment.tender == OrderPayment.Tender.CARD:
        if session is None or session.status != CashierSession.STATUS_OPEN:
            raise ValidationError({"session": ["Open cashier session is required."]})

    if payment.status != OrderPayment.Status.PENDING:
        raise ValidationError({"status": ["Payment is not pending."]})

    provider = registry.get_provider_for_payment(payment)
    payload = provider.authorize(payment=payment, timeout_s=timeout_s)

    payment.status = OrderPayment.Status.AUTHORIZED
    payment.authorized_at = timezone.now()
    payment.raw_provider_payload = payload
    payment.save(update_fields=["status", "authorized_at", "raw_provider_payload", "updated_at"])

    return payment
