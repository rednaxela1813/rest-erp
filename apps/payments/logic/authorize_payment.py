from __future__ import annotations

from django.utils import timezone
from rest_framework.exceptions import ValidationError
import structlog

from apps.payments.models import CashierSession, OrderPayment
from apps.payments.providers import registry

logger = structlog.get_logger(__name__)


def authorize_payment(
    *,
    payment: OrderPayment,
    actor=None,
    terminal=None,
    session: CashierSession | None,
    timeout_s: int = 30,
) -> OrderPayment:
    logger.info(
        "payment_authorize_started",
        payment_id=str(payment.public_id),
        order_id=str(payment.order.public_id),
        tender=payment.tender,
        provider=payment.provider,
        session_id=str(session.public_id) if session else "",
        actor_id=str(actor.id) if actor else "",
    )
    if payment.tender == OrderPayment.Tender.CARD:
        if session is None or session.status != CashierSession.STATUS_OPEN:
            logger.warning(
                "payment_authorize_missing_open_session",
                payment_id=str(payment.public_id),
                order_id=str(payment.order.public_id),
                tender=payment.tender,
            )
            raise ValidationError({"session": ["Open cashier session is required."]})

    if payment.status != OrderPayment.Status.PENDING:
        logger.warning(
            "payment_authorize_invalid_status",
            payment_id=str(payment.public_id),
            order_id=str(payment.order.public_id),
            status=payment.status,
        )
        raise ValidationError({"status": ["Payment is not pending."]})

    provider = registry.get_provider_for_payment(payment)
    payload = provider.authorize(payment=payment, timeout_s=timeout_s)

    payment.status = OrderPayment.Status.AUTHORIZED
    payment.authorized_at = timezone.now()
    payment.raw_provider_payload = payload
    payment.save(update_fields=["status", "authorized_at", "raw_provider_payload", "updated_at"])

    logger.info(
        "payment_authorize_succeeded",
        payment_id=str(payment.public_id),
        order_id=str(payment.order.public_id),
        status=payment.status,
    )
    return payment
