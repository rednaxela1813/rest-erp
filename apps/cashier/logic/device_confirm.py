from __future__ import annotations

from django.shortcuts import get_object_or_404

from apps.payments.models import CashierSession, OrderPayment

from .payment_confirm import confirm_card_payment, confirm_cash_payment


class OpenCashierSessionRequired(RuntimeError):
    pass


def confirm_device_cash_payment(*, public_id, logger) -> OrderPayment:
    payment, session = _get_payment_and_open_session(public_id=public_id)
    confirm_cash_payment(payment=payment, actor=None, session=session)
    logger.info("cashier_device_cash_confirm_succeeded", payment_id=str(payment.public_id))
    return payment


def confirm_device_card_payment(*, public_id, logger) -> OrderPayment:
    payment, session = _get_payment_and_open_session(public_id=public_id)
    confirm_card_payment(payment=payment, actor=None, session=session)
    logger.info("cashier_device_card_confirm_succeeded", payment_id=str(payment.public_id))
    return payment


def _get_payment_and_open_session(*, public_id) -> tuple[OrderPayment, CashierSession]:
    payment = get_object_or_404(OrderPayment, public_id=public_id)
    session = (
        CashierSession.objects.select_related("org", "terminal")
        .filter(org=payment.org, status=CashierSession.STATUS_OPEN)
        .first()
    )
    if session is None:
        raise OpenCashierSessionRequired
    return payment, session
