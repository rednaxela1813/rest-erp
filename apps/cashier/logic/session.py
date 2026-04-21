"""
Cashier session management.

Открытие/закрытие смены, получение активной сессии, управление кассовым ящиком.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpRequest

from apps.payments.models import CashDrawerMovement, CashierSession
from config.orgs.models import Organization

from .cart import SESSION_ORG_ID, SESSION_SESSION_ID


def get_active_org(request: HttpRequest) -> Organization | None:
    org_id = request.session.get(SESSION_ORG_ID)
    if not org_id:
        return None
    return Organization.objects.filter(public_id=org_id, members__user=request.user).first()


def get_active_session(request: HttpRequest) -> CashierSession | None:
    session_id = request.session.get(SESSION_SESSION_ID)
    if not session_id:
        return None
    session = (
        CashierSession.objects.select_related("org", "terminal")
        .filter(pk=session_id, cashier=request.user, status=CashierSession.STATUS_OPEN)
        .first()
    )
    if session is None:
        request.session.pop(SESSION_SESSION_ID, None)
        request.session.pop(SESSION_ORG_ID, None)
    return session


def cash_drawer_total(session: CashierSession) -> Decimal:
    """
    Считает текущий остаток в кассовом ящике.
    Формула: opening_float + sale_cash + cash_in - cash_out.
    """
    cash_movements = session.cash_movements.aggregate(
        sale_cash=Coalesce(
            Sum("amount", filter=Q(movement_type=CashDrawerMovement.Type.SALE_CASH)),
            Value(Decimal("0.00")),
        ),
        cash_in=Coalesce(
            Sum("amount", filter=Q(movement_type=CashDrawerMovement.Type.CASH_IN)),
            Value(Decimal("0.00")),
        ),
        cash_out=Coalesce(
            Sum("amount", filter=Q(movement_type=CashDrawerMovement.Type.CASH_OUT)),
            Value(Decimal("0.00")),
        ),
    )
    return (
        session.cash_drawer_start + cash_movements["sale_cash"] + cash_movements["cash_in"] - cash_movements["cash_out"]
    ).quantize(Decimal("0.01"))
