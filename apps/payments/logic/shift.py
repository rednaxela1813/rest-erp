from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.orders.models import OrderItem
from apps.payments.models import CashierSession, OrderPayment


def open_shift(*, org, terminal, cashier, opening_cash: Decimal) -> CashierSession:
    """
    Open a cashier shift (CashierSession).

    Rules:
    - Only one open session per terminal/org.
    - If the same cashier tries to open again, return existing session (idempotent).
    """
    with transaction.atomic():
        existing = (
            CashierSession.objects
            .select_for_update()
            .filter(org=org, terminal=terminal, status=CashierSession.STATUS_OPEN)
            .first()
        )
        if existing:
            if existing.cashier_id != cashier.id:
                raise ValidationError({"session": ["Terminal already has an open shift."]})
            return existing

        return CashierSession.objects.create(
            org=org,
            terminal=terminal,
            cashier=cashier,
            cash_drawer_start=opening_cash,
            status=CashierSession.STATUS_OPEN,
        )


def close_shift(*, session: CashierSession, closing_cash: Decimal) -> CashierSession:
    """
    Close an open cashier shift.

    Rules:
    - Only open sessions can be closed.
    - Closing sets cash drawer end amount and closed_at timestamp.
    """
    if session.status != CashierSession.STATUS_OPEN:
        raise ValidationError({"session": ["Shift is already closed."]})

    session.status = CashierSession.STATUS_CLOSED
    session.cash_drawer_end = closing_cash
    session.closed_at = timezone.now()
    session.save(update_fields=["status", "cash_drawer_end", "closed_at", "updated_at"])
    return session


def _line_tax_amount(*, qty: Decimal, unit_price: Decimal, rate: Decimal) -> Decimal:
    """
    Calculate VAT amount from a VAT-inclusive line total.
    Rounds tax per line to avoid cumulative rounding errors.
    """
    line_total = (qty * unit_price).quantize(Decimal("0.01"))
    if rate <= 0:
        return Decimal("0.00")
    divisor = Decimal("1.00") + (rate / Decimal("100"))
    return (line_total - (line_total / divisor)).quantize(Decimal("0.01"))


def shift_report(*, session: CashierSession) -> dict:
    """
    Build a shift report with totals by tender and tax rate.

    Scope:
    - Payments linked to session terminal
    - Payments created between opened_at and closed_at (or now if still open)
    """
    end_ts = session.closed_at or timezone.now()

    payments = (
        OrderPayment.objects
        .filter(
            org=session.org,
            terminal=session.terminal,
            status=OrderPayment.Status.CAPTURED,
            created_at__gte=session.opened_at,
            created_at__lte=end_ts,
        )
        .select_related("order")
    )

    total_amount = sum((p.amount for p in payments), Decimal("0.00"))
    totals_by_tender: dict[str, Decimal] = {}
    for payment in payments:
        totals_by_tender[payment.tender] = totals_by_tender.get(payment.tender, Decimal("0.00")) + payment.amount

    # Aggregate tax by rate using order items in the same window.
    order_ids = [p.order_id for p in payments if p.order_id]
    items = (
        OrderItem.objects
        .filter(order_id__in=order_ids)
        .select_related("tax_rate")
    )

    tax_by_rate: dict[str, Decimal] = {}
    total_tax = Decimal("0.00")
    for item in items:
        rate = item.tax_rate.rate if item.tax_rate else Decimal("0.00")
        tax_amount = _line_tax_amount(qty=item.qty, unit_price=item.unit_price, rate=rate)
        total_tax += tax_amount
        key = str(rate.quantize(Decimal("0.01")))
        tax_by_rate[key] = tax_by_rate.get(key, Decimal("0.00")) + tax_amount

    return {
        "payments_total": total_amount.quantize(Decimal("0.01")),
        "tax_total": total_tax.quantize(Decimal("0.01")),
        "by_tender": {k: v.quantize(Decimal("0.01")) for k, v in totals_by_tender.items()},
        "by_tax_rate": [
            {"rate": rate, "tax_total": amount.quantize(Decimal("0.01"))}
            for rate, amount in sorted(tax_by_rate.items())
        ],
    }
