from __future__ import annotations

from rest_framework.exceptions import ValidationError

from apps.payments.logic.order_adjustments import refund_paid_order
from apps.payments.models import CashierSession, OrderPayment

from .cart import SESSION_REFUND_ERROR
from .cash_drawer import record_cash_refund
from .ekasa import trigger_ekasa_processing


def refund_order_from_cashier(*, request, order, session: CashierSession, logger) -> None:
    logger.info(
        "cashier_order_refund_started",
        org_id=str(session.org.public_id),
        order_id=str(order.public_id),
        user_id=str(request.user.id),
    )

    try:
        refund_paid_order(order=order, actor=request.user)

        payment = order.payments.filter(status=OrderPayment.Status.CAPTURED).first()
        if payment and payment.tender == OrderPayment.Tender.CASH:
            record_cash_refund(
                payment=payment,
                session=session,
                actor=request.user,
                reason=f"Refund: order {order.public_id}",
            )
        trigger_ekasa_processing(session.org_id)
        logger.info(
            "cashier_order_refund_succeeded",
            org_id=str(session.org.public_id),
            order_id=str(order.public_id),
            tender=payment.tender if payment else "",
        )
    except ValidationError as exc:
        logger.warning(
            "cashier_order_refund_failed",
            org_id=str(session.org.public_id),
            order_id=str(order.public_id),
            error=str(exc),
        )
        request.session[SESSION_REFUND_ERROR] = str(exc)
