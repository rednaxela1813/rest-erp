from __future__ import annotations

from apps.payments.models import CashDrawerMovement, CashierSession, OrderPayment


def record_cash_sale(*, payment: OrderPayment, session: CashierSession, actor) -> CashDrawerMovement:
    return CashDrawerMovement.objects.create(
        session=session,
        actor=actor,
        movement_type=CashDrawerMovement.Type.SALE_CASH,
        amount=payment.amount,
    )


def record_cash_refund(*, payment: OrderPayment, session: CashierSession, actor, reason: str) -> CashDrawerMovement:
    return CashDrawerMovement.objects.create(
        session=session,
        actor=actor,
        movement_type=CashDrawerMovement.Type.CASH_OUT,
        amount=payment.amount,
        reason=reason,
    )
