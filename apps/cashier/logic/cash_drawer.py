from __future__ import annotations

from decimal import Decimal, InvalidOperation

from apps.payments.models import CashDrawerMovement, CashierSession, OrderPayment


def parse_amount(raw_value: str) -> Decimal:
    try:
        return Decimal(raw_value).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        return Decimal("0.00")


def record_opening_float(*, session: CashierSession, actor, amount: Decimal) -> CashDrawerMovement | None:
    if amount <= Decimal("0.00"):
        return None
    return CashDrawerMovement.objects.create(
        session=session,
        actor=actor,
        movement_type=CashDrawerMovement.Type.OPENING_FLOAT,
        amount=amount,
    )


def record_cash_in(*, session: CashierSession, actor, raw_amount: str, reason: str) -> CashDrawerMovement | None:
    amount = parse_amount(raw_amount)
    if amount <= Decimal("0.00"):
        return None
    return CashDrawerMovement.objects.create(
        session=session,
        actor=actor,
        movement_type=CashDrawerMovement.Type.CASH_IN,
        amount=amount,
        reason=reason.strip(),
    )


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
