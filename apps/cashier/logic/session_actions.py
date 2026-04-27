from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.contrib.auth import logout
from django.http import HttpRequest

from apps.payments.logic.shift import close_shift, shift_report
from apps.payments.models import CashDrawerMovement, CashierSession, Terminal
from config.orgs.models import Organization

from .cart import SESSION_CART, SESSION_ORG_ID, SESSION_SESSION_ID
from .session import cash_drawer_total


@dataclass(frozen=True)
class SessionOpenResult:
    context: dict
    redirect_to_home: bool = False


def parse_amount(raw_value: str) -> Decimal:
    try:
        return Decimal(raw_value).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        return Decimal("0.00")


def open_cashier_session(*, request: HttpRequest, logger) -> SessionOpenResult:
    orgs = Organization.objects.filter(members__user=request.user).distinct().order_by("name")
    terminals = Terminal.objects.filter(org__in=orgs, status=Terminal.STATUS_ACTIVE).select_related("org")
    error = ""
    selected_org_id = ""
    selected_terminal_id = ""
    opening_cash_value = "0.00"

    if request.method == "POST":
        selected_org_id = request.POST.get("org_id", "")
        selected_terminal_id = request.POST.get("terminal_id", "")
        opening_cash_value = request.POST.get("opening_cash", "0.00")
        opening_cash = parse_amount(opening_cash_value)

        logger.info(
            "cashier_session_open_requested",
            user_id=str(request.user.id),
            requested_org_id=selected_org_id,
            opening_cash=str(opening_cash),
        )

        org = Organization.objects.filter(public_id=selected_org_id, members__user=request.user).first()
        terminal = None
        if org:
            if selected_terminal_id:
                terminal = Terminal.objects.filter(id=selected_terminal_id, org=org).first()
            else:
                terminal, _ = Terminal.objects.get_or_create(
                    org=org,
                    code="virtual",
                    defaults={"name": "Virtual POS", "status": Terminal.STATUS_ACTIVE},
                )
                if terminal.status != Terminal.STATUS_ACTIVE:
                    terminal.status = Terminal.STATUS_ACTIVE
                    terminal.save(update_fields=["status"])

        if org is None or terminal is None:
            logger.warning(
                "cashier_session_open_invalid_selection",
                user_id=str(request.user.id),
                requested_org_id=selected_org_id,
                requested_terminal_id=selected_terminal_id,
            )
            error = "Select organization and terminal."
        else:
            existing = CashierSession.objects.filter(
                org=org,
                terminal=terminal,
                status=CashierSession.STATUS_OPEN,
            ).first()
            if existing:
                if existing.cashier_id == request.user.id:
                    request.session[SESSION_ORG_ID] = str(org.public_id)
                    request.session[SESSION_SESSION_ID] = existing.id
                    request.session.setdefault(SESSION_CART, {})
                    return SessionOpenResult(context={}, redirect_to_home=True)
                error = "Terminal already has an open session."
            else:
                session = CashierSession.objects.create(
                    org=org,
                    terminal=terminal,
                    cashier=request.user,
                    cash_drawer_start=opening_cash,
                )
                if opening_cash > Decimal("0.00"):
                    CashDrawerMovement.objects.create(
                        session=session,
                        actor=request.user,
                        movement_type=CashDrawerMovement.Type.OPENING_FLOAT,
                        amount=opening_cash,
                    )
                logger.info(
                    "cashier_session_open_succeeded",
                    user_id=str(request.user.id),
                    org_id=str(org.public_id),
                    session_id=str(session.public_id),
                )
                request.session[SESSION_ORG_ID] = str(org.public_id)
                request.session[SESSION_SESSION_ID] = session.id
                request.session[SESSION_CART] = {}
                return SessionOpenResult(context={}, redirect_to_home=True)

    return SessionOpenResult(
        context={
            "orgs": orgs,
            "terminals": terminals,
            "error": error,
            "selected_org_id": selected_org_id,
            "selected_terminal_id": selected_terminal_id,
            "opening_cash_value": opening_cash_value,
        }
    )


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


def record_cash_in(*, session: CashierSession, actor, raw_amount: str, reason: str) -> None:
    amount = parse_amount(raw_amount)
    if amount <= Decimal("0.00"):
        return
    CashDrawerMovement.objects.create(
        session=session,
        actor=actor,
        movement_type=CashDrawerMovement.Type.CASH_IN,
        amount=amount,
        reason=reason.strip(),
    )
