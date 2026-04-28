from __future__ import annotations

from rest_framework.exceptions import ValidationError

from apps.payments.logic.authorize_payment import authorize_payment
from apps.payments.logic.capture_payment import capture_payment
from apps.payments.models import CashierSession, OrderPayment

from .receipts import send_receipts


def confirm_card_payment(*, payment: OrderPayment, actor, session: CashierSession) -> OrderPayment:
    """
    Подтверждает карточную оплату через authorize → capture цепочку.
    Отправляет чек после успешного capture.
    """
    if payment.status == OrderPayment.Status.CAPTURED:
        return payment

    if payment.status == OrderPayment.Status.PENDING:
        try:
            authorize_payment(payment=payment, actor=actor, terminal=session.terminal, session=session)
            payment.refresh_from_db()
        except ValidationError as exc:
            payment.status = OrderPayment.Status.FAILED
            payment.failure_reason = str(exc)
            payment.save(update_fields=["status", "failure_reason", "updated_at"])
            return payment

    if payment.status == OrderPayment.Status.AUTHORIZED:
        try:
            capture_payment(payment=payment, actor=actor)
            payment.refresh_from_db()
        except ValidationError as exc:
            payment.status = OrderPayment.Status.FAILED
            payment.failure_reason = str(exc)
            payment.save(update_fields=["status", "failure_reason", "updated_at"])
            return payment

    send_receipts(order=payment.order, payment=payment, session=session)
    return payment
