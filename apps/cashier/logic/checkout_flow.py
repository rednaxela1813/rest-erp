from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.db import IntegrityError
from django.http import HttpRequest

from apps.payments.models import CashierSession, OrderPayment

from .cart import (
    SESSION_CHECKOUT_ERROR,
    SESSION_CHECKOUT_IDEMPOTENCY,
    cart_fingerprint,
    cart_items,
    get_cart,
)
from .order_builder import build_order_from_cart
from .payment_confirm import confirm_card_payment, confirm_cash_payment, create_payment


@dataclass(frozen=True)
class CheckoutResult:
    payment: OrderPayment | None = None
    redirect_home: bool = False


def checkout_cart(*, request: HttpRequest, session: CashierSession, logger) -> CheckoutResult:
    cart = get_cart(request.session)
    items = cart_items(cart, session.org)
    tender = request.POST.get("tender")

    logger.info(
        "cashier_checkout_requested",
        org_id=str(session.org.public_id),
        session_id=str(session.public_id),
        user_id=str(request.user.id),
        tender=tender or "",
        cart_items_count=len(items),
    )

    if not items:
        return CheckoutResult(redirect_home=True)

    if tender not in (OrderPayment.Tender.CASH, OrderPayment.Tender.CARD):
        return CheckoutResult(redirect_home=True)

    fingerprint = cart_fingerprint(cart=cart, tender=tender)
    idem_map = request.session.get(SESSION_CHECKOUT_IDEMPOTENCY)
    if not isinstance(idem_map, dict):
        idem_map = {}
        request.session[SESSION_CHECKOUT_IDEMPOTENCY] = idem_map

    idempotency_key = idem_map.get(fingerprint)
    if idempotency_key:
        existing = OrderPayment.objects.filter(org=session.org, idempotency_key=idempotency_key).first()
        if existing:
            return CheckoutResult(payment=existing)
    else:
        idempotency_key = uuid.uuid4().hex
        idem_map[fingerprint] = idempotency_key
        request.session.modified = True

    try:
        order = build_order_from_cart(org=session.org, cart_items=items)
    except ValueError:
        logger.warning(
            "cashier_checkout_invalid_product_config",
            org_id=str(session.org.public_id),
            session_id=str(session.public_id),
            user_id=str(request.user.id),
        )
        request.session[SESSION_CHECKOUT_ERROR] = "Cannot checkout: one or more products are missing unit or tax rate."
        return CheckoutResult(redirect_home=True)

    try:
        payment = create_payment(
            order=order,
            session=session,
            tender=tender,
            idempotency_key=idempotency_key,
        )
    except IntegrityError:
        existing = OrderPayment.objects.filter(org=session.org, idempotency_key=idempotency_key).first()
        if existing:
            return CheckoutResult(payment=existing)
        raise

    cart.clear()
    request.session.modified = True

    if tender == OrderPayment.Tender.CASH:
        confirm_cash_payment(payment=payment, actor=request.user, session=session)
    else:
        confirm_card_payment(payment=payment, actor=request.user, session=session)

    logger.info(
        "cashier_checkout_created_payment",
        org_id=str(session.org.public_id),
        payment_id=str(payment.public_id),
        tender=tender,
        payment_status=payment.status,
    )
    return CheckoutResult(payment=payment)
