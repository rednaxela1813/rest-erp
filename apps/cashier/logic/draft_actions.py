from __future__ import annotations

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.orders.logic.cancel_draft_order import cancel_draft_order
from apps.orders.models import Order
from apps.payments.models import CashierSession, OrderPayment
from config.orgs.models import Organization

from .payment_confirm import create_payment

VALID_DRAFT_TENDERS = (OrderPayment.Tender.CASH, OrderPayment.Tender.CARD)


def start_draft_payment(*, org: Organization, public_id, session: CashierSession, tender: str) -> OrderPayment | None:
    if tender not in VALID_DRAFT_TENDERS:
        return None

    order = get_object_or_404(Order, org=org, public_id=public_id)
    if order.status != Order.STATUS_DRAFT or not order.items.exists():
        return None

    order.recompute_totals()
    order.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])

    idempotency_key = f"draft:{order.public_id}:{tender}"
    existing = OrderPayment.objects.filter(org=org, idempotency_key=idempotency_key).first()
    if existing:
        return existing

    try:
        return create_payment(
            order=order,
            session=session,
            tender=tender,
            idempotency_key=idempotency_key,
        )
    except IntegrityError:
        existing = OrderPayment.objects.filter(org=org, idempotency_key=idempotency_key).first()
        if existing:
            return existing
        raise


def cancel_draft_from_cashier(*, org: Organization, public_id, actor) -> None:
    order = get_object_or_404(Order, org=org, public_id=public_id)
    try:
        cancel_draft_order(order=order, actor=actor)
    except ValidationError:
        pass
