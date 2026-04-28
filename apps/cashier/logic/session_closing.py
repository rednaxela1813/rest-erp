from __future__ import annotations

from django.contrib.auth import logout
from django.http import HttpRequest

from apps.payments.logic.shift import close_shift, shift_report
from apps.payments.models import CashierSession

from .cart import SESSION_CART, SESSION_ORG_ID, SESSION_SESSION_ID
from .session import cash_drawer_total


def build_session_close_context(*, session: CashierSession, default_currency: str) -> dict:
    drawer_total = cash_drawer_total(session)
    return {
        "session": session,
        "org": session.org,
        "report": shift_report(session=session),
        "cash_drawer_total": drawer_total,
        "currency": default_currency,
    }


def close_cashier_session(*, request: HttpRequest, session: CashierSession) -> None:
    close_shift(session=session, closing_cash=cash_drawer_total(session))
    logout(request)
    request.session.pop(SESSION_ORG_ID, None)
    request.session.pop(SESSION_SESSION_ID, None)
    request.session.pop(SESSION_CART, None)
