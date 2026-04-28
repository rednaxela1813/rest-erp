from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Sum, Value
from django.db.models.functions import Coalesce

from apps.orders.models import Order
from apps.payments.models import CashierSession, OrderPayment

from .cart import cart_items, cart_totals, get_cart, get_products
from .session import cash_drawer_total


def cashier_home_context(*, request_session, session: CashierSession, cart_error: str, refund_error: str) -> dict:
    org = session.org
    products = get_products(org)
    cart = get_cart(request_session)
    items = cart_items(cart, org)
    totals = cart_totals(items)

    draft_orders = (
        Order.objects.filter(org=org, status=Order.STATUS_DRAFT)
        .annotate(items_count=Count("items"))
        .filter(items_count__gt=0)
        .order_by("-created_at")[:10]
    )
    paid_orders = Order.objects.filter(org=org, status=Order.STATUS_PAID).order_by("-created_at")[:10]
    todays_sales_total = (
        OrderPayment.objects.filter(
            org=org,
            terminal=session.terminal,
            status=OrderPayment.Status.CAPTURED,
            tender__in=[OrderPayment.Tender.CASH, OrderPayment.Tender.CARD],
            captured_at__gte=session.opened_at,
        ).aggregate(total=Coalesce(Sum("amount"), Value(Decimal("0.00"))))["total"]
    ).quantize(Decimal("0.01"))

    return {
        "org": org,
        "session": session,
        "products": products,
        "cart_items": items,
        "cart_count": sum(cart.values()) if cart else 0,
        "totals": totals,
        "currency": settings.DEFAULT_CURRENCY,
        "draft_orders": draft_orders,
        "paid_orders": paid_orders,
        "cash_drawer_total": cash_drawer_total(session),
        "todays_sales_total": todays_sales_total,
        "cart_error": cart_error,
        "refund_error": refund_error,
    }
