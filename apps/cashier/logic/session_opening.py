from __future__ import annotations

from dataclasses import dataclass

from django.http import HttpRequest

from apps.payments.models import CashierSession, Terminal
from config.orgs.models import Organization

from .cart import SESSION_CART, SESSION_ORG_ID, SESSION_SESSION_ID
from .cash_drawer import parse_amount, record_opening_float


@dataclass(frozen=True)
class SessionOpenResult:
    context: dict
    redirect_to_home: bool = False


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
        terminal = _find_or_create_terminal(org=org, selected_terminal_id=selected_terminal_id)

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
                    _store_session(request=request, org=org, session=existing)
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
                record_opening_float(session=session, actor=request.user, amount=opening_cash)
                logger.info(
                    "cashier_session_open_succeeded",
                    user_id=str(request.user.id),
                    org_id=str(org.public_id),
                    session_id=str(session.public_id),
                )
                _store_session(request=request, org=org, session=session)
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


def _find_or_create_terminal(*, org, selected_terminal_id: str) -> Terminal | None:
    if org is None:
        return None
    if selected_terminal_id:
        return Terminal.objects.filter(id=selected_terminal_id, org=org).first()

    terminal, _ = Terminal.objects.get_or_create(
        org=org,
        code="virtual",
        defaults={"name": "Virtual POS", "status": Terminal.STATUS_ACTIVE},
    )
    if terminal.status != Terminal.STATUS_ACTIVE:
        terminal.status = Terminal.STATUS_ACTIVE
        terminal.save(update_fields=["status"])
    return terminal


def _store_session(*, request: HttpRequest, org: Organization, session: CashierSession) -> None:
    request.session[SESSION_ORG_ID] = str(org.public_id)
    request.session[SESSION_SESSION_ID] = session.id
