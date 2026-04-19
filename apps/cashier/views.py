"""
Cashier views — тонкий HTTP-слой.

Каждый view делает только три вещи:
  1. Читает HTTP-запрос (POST-параметры, session, URL-kwargs)
  2. Вызывает логику из cashier/logic/
  3. Возвращает render() или redirect()

Бизнес-логика, ORM-запросы и вычисления — в logic/.
"""
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from decimal import Decimal, InvalidOperation

import structlog
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from apps.orders.models import KitchenTicket, Order
from apps.payments.logic.enqueue_device_commands import _build_fiscal_items, enqueue_payment_commands
from apps.payments.logic.shift import close_shift, shift_report
from apps.payments.models import CashDrawerMovement, CashierSession, DeviceCommand, OrderPayment, Terminal
from apps.products.models import Product
from config.orgs.models import Organization

from .logic.cart import (
    SESSION_CART,
    SESSION_CHECKOUT_ERROR,
    SESSION_CHECKOUT_IDEMPOTENCY,
    SESSION_ORG_ID,
    SESSION_REFUND_ERROR,
    SESSION_SESSION_ID,
    build_cart_context,
    cart_fingerprint,
    cart_items,
    cart_totals,
    get_cart,
    get_products,
    reset_checkout_idempotency,
    restore_cart_from_payload,
)
from .logic.order_builder import build_order_from_cart, product_checkout_error
from .logic.kitchen import kitchen_context
from .logic.payment_confirm import (
    confirm_card_payment,
    confirm_cash_payment,
    create_payment,
    trigger_ekasa_processing,
)
from .logic.session import cash_drawer_total, get_active_session

logger = structlog.get_logger(__name__)


# ── Utility ──────────────────────────────────────────────────────────────────

def _parse_amount(raw_value: str) -> Decimal:
    try:
        return Decimal(raw_value).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        return Decimal("0.00")


def _require_session_or_redirect(request: HttpRequest) -> CashierSession | HttpResponse:
    session = get_active_session(request)
    if session is None:
        return redirect("cashier:session_open")
    return session


def _device_signature_ok(request: HttpRequest) -> bool:
    token = settings.CASHIER_DEVICE_TOKEN
    if not token:
        return False

    timestamp = request.headers.get("X-DEVICE-TS", "")
    signature = request.headers.get("X-DEVICE-SIG", "")
    if not timestamp or not signature:
        return False

    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        return False

    if abs(int(time.time()) - timestamp_value) > 60:
        return False

    payload = f"{timestamp}.{request.body.decode('utf-8')}".encode("utf-8")
    expected_signature = hmac.new(
        key=token.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected_signature)


def _device_auth_failed_response(request: HttpRequest) -> HttpResponse:
    logger.warning(
        "device_auth_failed",
        ip=request.META.get("REMOTE_ADDR"),
    )
    return HttpResponse("invalid device signature", status=401)


# ── Auth ─────────────────────────────────────────────────────────────────────

@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def cashier_login(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("cashier:session_open")

    error = ""
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        user = authenticate(request, email=email, password=password)
        if user is not None:
            login(request, user)
            return redirect("cashier:session_open")
        error = "Invalid email or password."

    return render(request, "cashier/login.html", {"error": error})


@login_required
@require_http_methods(["POST"])
def cashier_logout(request: HttpRequest) -> HttpResponse:
    active_session = get_active_session(request)
    if active_session and active_session.status == CashierSession.STATUS_OPEN:
        closing_cash = cash_drawer_total(active_session)
        close_shift(session=active_session, closing_cash=closing_cash)
    logout(request)
    request.session.pop(SESSION_ORG_ID, None)
    request.session.pop(SESSION_SESSION_ID, None)
    request.session.pop(SESSION_CART, None)
    return redirect("cashier:login")


# ── Session open/close ───────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET", "POST"])
def session_open(request: HttpRequest) -> HttpResponse:
    active_session = get_active_session(request)
    if active_session:
        return redirect("cashier:home")

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
        opening_cash = _parse_amount(opening_cash_value)

        logger.info(
            "cashier_session_open_requested",
            user_id=str(request.user.id),
            requested_org_id=selected_org_id,
            opening_cash=str(opening_cash),
        )

        org = Organization.objects.filter(
            public_id=selected_org_id, members__user=request.user
        ).first()
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
                org=org, terminal=terminal, status=CashierSession.STATUS_OPEN,
            ).first()
            if existing:
                if existing.cashier_id == request.user.id:
                    request.session[SESSION_ORG_ID] = str(org.public_id)
                    request.session[SESSION_SESSION_ID] = existing.id
                    request.session.setdefault(SESSION_CART, {})
                    return redirect("cashier:home")
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
                return redirect("cashier:home")

    return render(
        request,
        "cashier/session_open.html",
        {
            "orgs": orgs,
            "terminals": terminals,
            "error": error,
            "selected_org_id": selected_org_id,
            "selected_terminal_id": selected_terminal_id,
            "opening_cash_value": opening_cash_value,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def session_close(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    report = shift_report(session=session)
    drawer_total = cash_drawer_total(session)

    if request.method == "POST":
        close_shift(session=session, closing_cash=drawer_total)
        logout(request)
        request.session.pop(SESSION_ORG_ID, None)
        request.session.pop(SESSION_SESSION_ID, None)
        request.session.pop(SESSION_CART, None)
        return redirect("cashier:login")

    return render(request, "cashier/session_close.html", {
        "session": session,
        "org": session.org,
        "report": report,
        "cash_drawer_total": drawer_total,
        "currency": settings.DEFAULT_CURRENCY,
    })


@login_required
@require_http_methods(["POST"])
def cash_in(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    amount = _parse_amount(request.POST.get("amount", "0"))
    reason = request.POST.get("reason", "").strip()
    if amount > Decimal("0.00"):
        CashDrawerMovement.objects.create(
            session=session,
            actor=request.user,
            movement_type=CashDrawerMovement.Type.CASH_IN,
            amount=amount,
            reason=reason,
        )
    return redirect("cashier:home")


# ── Main page ────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def cashier_home(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    org = session.org
    products = get_products(org)
    cart = get_cart(request.session)
    items = cart_items(cart, org)
    totals = cart_totals(items)

    draft_orders = (
        Order.objects
        .filter(org=org, status=Order.STATUS_DRAFT)
        .annotate(items_count=Count("items"))
        .filter(items_count__gt=0)
        .order_by("-created_at")[:10]
    )
    paid_orders = (
        Order.objects
        .filter(org=org, status=Order.STATUS_PAID)
        .order_by("-created_at")[:10]
    )
    drawer_total = cash_drawer_total(session)
    todays_sales_total = (
        OrderPayment.objects
        .filter(
            org=org,
            terminal=session.terminal,
            status=OrderPayment.Status.CAPTURED,
            tender__in=[OrderPayment.Tender.CASH, OrderPayment.Tender.CARD],
            captured_at__gte=session.opened_at,
        )
        .aggregate(total=Coalesce(Sum("amount"), Value(Decimal("0.00"))))["total"]
    ).quantize(Decimal("0.01"))

    return render(request, "cashier/index.html", {
        "org": org,
        "session": session,
        "products": products,
        "cart_items": items,
        "cart_count": sum(cart.values()) if cart else 0,
        "totals": totals,
        "currency": settings.DEFAULT_CURRENCY,
        "draft_orders": draft_orders,
        "paid_orders": paid_orders,
        "cash_drawer_total": drawer_total,
        "todays_sales_total": todays_sales_total,
        "cart_error": request.session.pop(SESSION_CHECKOUT_ERROR, ""),
        "refund_error": request.session.pop(SESSION_REFUND_ERROR, ""),
    })


# ── Product catalog ──────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def product_list(request: HttpRequest) -> HttpResponse:
    session = get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    query = request.GET.get("q", "").strip()
    return render(request, "cashier/partials/product_list.html", {
        "org": session.org,
        "products": get_products(session.org, query=query),
        "query": query,
        "currency": settings.DEFAULT_CURRENCY,
    })


# ── Cart ─────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def cart_panel(request: HttpRequest) -> HttpResponse:
    session = get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    cart = get_cart(request.session)
    return render(request, "cashier/partials/cart.html", build_cart_context(cart, session.org))


@login_required
@require_http_methods(["POST"])
def cart_add(request: HttpRequest, product_id: int) -> HttpResponse:
    session = get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    product = get_object_or_404(Product, id=product_id, org=session.org)
    cart = get_cart(request.session)
    error = ""
    if not product.unit or not product.tax_rate:
        error = product_checkout_error(product)
    else:
        key = str(product.id)
        cart[key] = cart.get(key, 0) + 1
        reset_checkout_idempotency(request.session)
        request.session.modified = True

    return render(request, "cashier/partials/cart.html",
                  build_cart_context(cart, session.org, last_added=product, cart_error=error))


@login_required
@require_http_methods(["POST"])
def cart_add_barcode(request: HttpRequest) -> HttpResponse:
    session = get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    barcode = request.POST.get("barcode", "").strip()
    product = Product.objects.filter(org=session.org, barcode=barcode).first()
    cart = get_cart(request.session)
    error = ""

    if not barcode:
        error = "Barcode is required."
    elif not product:
        error = f"Product with barcode {barcode} not found."
    elif not product.unit or not product.tax_rate:
        error = product_checkout_error(product)
    else:
        key = str(product.id)
        cart[key] = cart.get(key, 0) + 1
        reset_checkout_idempotency(request.session)
        request.session.modified = True

    return render(request, "cashier/partials/cart.html",
                  build_cart_context(cart, session.org, cart_error=error))


@login_required
@require_http_methods(["POST"])
def cart_remove(request: HttpRequest, product_id: int) -> HttpResponse:
    session = get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    product = get_object_or_404(Product, id=product_id, org=session.org)
    cart = get_cart(request.session)
    key = str(product.id)
    if key in cart:
        new_qty = cart[key] - 1
        if new_qty <= 0:
            cart.pop(key, None)
        else:
            cart[key] = new_qty
        reset_checkout_idempotency(request.session)
        request.session.modified = True

    return render(request, "cashier/partials/cart.html", build_cart_context(cart, session.org))


@login_required
@require_http_methods(["POST"])
def cart_clear(request: HttpRequest) -> HttpResponse:
    session = get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    cart = get_cart(request.session)
    cart.clear()
    reset_checkout_idempotency(request.session)
    request.session.modified = True

    return render(request, "cashier/partials/cart.html", {
        "org": session.org,
        "cart_items": [],
        "cart_count": 0,
        "totals": {"subtotal": Decimal("0.00"), "total": Decimal("0.00")},
        "currency": settings.DEFAULT_CURRENCY,
    })


@login_required
@require_http_methods(["POST"])
def cart_restore(request: HttpRequest) -> HttpResponse:
    session = get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    cart = restore_cart_from_payload(request.POST.get("items", "[]"), session.org)
    request.session[SESSION_CART] = cart
    reset_checkout_idempotency(request.session)
    request.session.modified = True

    return render(request, "cashier/partials/cart.html",
                  build_cart_context(cart, session.org, cart_error=""))


# ── Kitchen ──────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def kitchen_board(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    return render(request, "cashier/kitchen.html", {
        "org": session.org, "session": session, **kitchen_context(session.org),
    })


@login_required
@require_http_methods(["GET"])
def kitchen_panel(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    return render(request, "cashier/partials/kitchen_panel.html", kitchen_context(session.org))


@login_required
@require_http_methods(["POST"])
def kitchen_claim_next(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    with transaction.atomic():
        ticket = (
            KitchenTicket.objects
            .select_for_update()
            .filter(org=session.org, status=KitchenTicket.Status.PENDING)
            .order_by("created_at", "id")
            .first()
        )
        if ticket:
            ticket.status = KitchenTicket.Status.IN_PROGRESS
            ticket.save(update_fields=["status", "updated_at"])

    return render(request, "cashier/partials/kitchen_panel.html", kitchen_context(session.org))


@login_required
@require_http_methods(["POST"])
def kitchen_update(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    status_value = request.POST.get("status")
    allowed = {KitchenTicket.Status.IN_PROGRESS, KitchenTicket.Status.DONE, KitchenTicket.Status.CANCELLED}
    if status_value not in allowed:
        return HttpResponseBadRequest("invalid status")

    ticket = get_object_or_404(KitchenTicket, org=session.org, public_id=public_id)
    ticket.status = status_value
    ticket.save(update_fields=["status", "updated_at"])

    return render(request, "cashier/partials/kitchen_panel.html", kitchen_context(session.org))


# ── Checkout ─────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["POST"])
def checkout(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

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
        return redirect("cashier:home")

    if tender not in (OrderPayment.Tender.CASH, OrderPayment.Tender.CARD):
        return redirect("cashier:home")

    fingerprint = cart_fingerprint(cart=cart, tender=tender)
    idem_map = request.session.get(SESSION_CHECKOUT_IDEMPOTENCY)
    if not isinstance(idem_map, dict):
        idem_map = {}
        request.session[SESSION_CHECKOUT_IDEMPOTENCY] = idem_map

    idempotency_key = idem_map.get(fingerprint)
    if idempotency_key:
        existing = OrderPayment.objects.filter(
            org=session.org, idempotency_key=idempotency_key
        ).first()
        if existing:
            return redirect("cashier:payment_wait", public_id=existing.public_id)
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
        request.session[SESSION_CHECKOUT_ERROR] = (
            "Cannot checkout: one or more products are missing unit or tax rate."
        )
        return redirect("cashier:home")

    try:
        payment = create_payment(
            order=order, session=session, tender=tender, idempotency_key=idempotency_key,
        )
    except IntegrityError:
        existing = OrderPayment.objects.filter(
            org=session.org, idempotency_key=idempotency_key
        ).first()
        if existing:
            return redirect("cashier:payment_wait", public_id=existing.public_id)
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
    return redirect("cashier:payment_wait", public_id=payment.public_id)


# ── Payment pages ─────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def payment_wait(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    payment = get_object_or_404(OrderPayment, org=session.org, public_id=public_id)
    return render(request, "cashier/payment_wait.html", {
        "org": session.org,
        "session": session,
        "payment": payment,
        "order": payment.order,
        "currency": settings.DEFAULT_CURRENCY,
        "debug": settings.DEBUG,
        "ekasa_enabled": settings.EKASA_ENABLED,
    })


@login_required
@require_http_methods(["GET"])
def payment_status(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    payment = get_object_or_404(OrderPayment, org=session.org, public_id=public_id)

    if (
        settings.EKASA_ENABLED
        and payment.status == OrderPayment.Status.CAPTURED
        and payment.fiscal_status == OrderPayment.FiscalStatus.PENDING
    ):
        fiscal_types = [
            DeviceCommand.Type.FISCALIZE_SALE,
            DeviceCommand.Type.FISCALIZE_REFUND,
            DeviceCommand.Type.FISCALIZE_STORNO,
        ]
        if not DeviceCommand.objects.filter(payment=payment, command_type__in=fiscal_types).exists():
            include_kot = payment.order.kitchen_tickets.exists()
            enqueue_payment_commands(payment=payment, include_kot=include_kot, include_payment_capture=False)

        from apps.payments.tasks import process_device_commands_ekasa
        try:
            process_device_commands_ekasa.run(org_id=session.org_id, limit=50)
        except Exception as exc:
            logger.exception(
                "cashier_payment_status_inline_fiscal_failed",
                org_id=str(session.org.public_id),
                payment_id=str(payment.public_id),
                error=str(exc),
            )
            payment.fiscal_status = OrderPayment.FiscalStatus.FAILED
            payment.failure_reason = str(exc)
            payment.save(update_fields=["fiscal_status", "failure_reason", "updated_at"])
        payment.refresh_from_db()

    failed_fiscal_command = (
        DeviceCommand.objects
        .filter(
            payment=payment,
            command_type__in=[
                DeviceCommand.Type.FISCALIZE_SALE,
                DeviceCommand.Type.FISCALIZE_REFUND,
                DeviceCommand.Type.FISCALIZE_STORNO,
            ],
            status=DeviceCommand.Status.FAILED,
        )
        .order_by("-updated_at", "-created_at")
        .first()
    )
    return render(request, "cashier/partials/payment_status.html", {
        "payment": payment,
        "order": payment.order,
        "currency": settings.DEFAULT_CURRENCY,
        "ekasa_enabled": settings.EKASA_ENABLED,
        "fiscal_last_error": failed_fiscal_command.last_error if failed_fiscal_command else "",
        "can_retry_fiscal": (
            settings.EKASA_ENABLED
            and payment.status == OrderPayment.Status.CAPTURED
            and failed_fiscal_command is not None
        ),
    })


@login_required
@require_http_methods(["POST"])
def payment_retry_fiscal(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    payment = get_object_or_404(OrderPayment, org=session.org, public_id=public_id)
    if payment.status != OrderPayment.Status.CAPTURED:
        return redirect("cashier:payment_wait", public_id=payment.public_id)

    logger.info(
        "cashier_payment_retry_fiscal_started",
        org_id=str(session.org.public_id),
        payment_id=str(payment.public_id),
    )

    sale_command = (
        DeviceCommand.objects
        .filter(payment=payment, command_type=DeviceCommand.Type.FISCALIZE_SALE)
        .order_by("-created_at")
        .first()
    )
    if sale_command is None:
        include_kot = payment.order.kitchen_tickets.exists()
        enqueue_payment_commands(payment=payment, include_kot=include_kot, include_payment_capture=False)
        sale_command = (
            DeviceCommand.objects
            .filter(payment=payment, command_type=DeviceCommand.Type.FISCALIZE_SALE)
            .order_by("-created_at")
            .first()
        )

    if sale_command is not None:
        sale_command.payload = {
            "order_id": str(payment.order.public_id),
            "payment_id": str(payment.public_id),
            "amount": str(payment.amount),
            "currency": payment.currency,
            "tender": payment.tender,
            "items": _build_fiscal_items(payment=payment),
        }
        sale_command.status = DeviceCommand.Status.PENDING
        sale_command.retries = 0
        sale_command.last_error = ""
        sale_command.next_attempt_at = None
        sale_command.save(
            update_fields=["payload", "status", "retries", "last_error", "next_attempt_at", "updated_at"]
        )

    payment.fiscal_status = OrderPayment.FiscalStatus.PENDING
    payment.failure_reason = ""
    payment.save(update_fields=["fiscal_status", "failure_reason", "updated_at"])
    trigger_ekasa_processing(payment.org_id)
    logger.info(
        "cashier_payment_retry_fiscal_succeeded",
        org_id=str(session.org.public_id),
        payment_id=str(payment.public_id),
        sale_command_id=str(sale_command.public_id) if sale_command else "",
    )
    return redirect("cashier:payment_wait", public_id=payment.public_id)


@login_required
@require_http_methods(["POST"])
def payment_confirm_cash(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    payment = get_object_or_404(OrderPayment, org=session.org, public_id=public_id)
    confirm_cash_payment(payment=payment, actor=request.user, session=session)
    return redirect("cashier:payment_wait", public_id=payment.public_id)


@login_required
@require_http_methods(["POST"])
def payment_confirm_card(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    payment = get_object_or_404(OrderPayment, org=session.org, public_id=public_id)
    confirm_card_payment(payment=payment, actor=request.user, session=session)
    return redirect("cashier:payment_wait", public_id=payment.public_id)


# ── Draft orders ─────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["POST"])
def draft_pay(request: HttpRequest, public_id, tender: str) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    if tender not in (OrderPayment.Tender.CASH, OrderPayment.Tender.CARD):
        return redirect("cashier:home")

    order = get_object_or_404(Order, org=session.org, public_id=public_id)
    if order.status != Order.STATUS_DRAFT or not order.items.exists():
        return redirect("cashier:home")

    order.recompute_totals()
    order.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])

    idempotency_key = f"draft:{order.public_id}:{tender}"
    existing = OrderPayment.objects.filter(org=session.org, idempotency_key=idempotency_key).first()
    if existing:
        return redirect("cashier:payment_wait", public_id=existing.public_id)

    try:
        payment = create_payment(
            order=order, session=session, tender=tender, idempotency_key=idempotency_key,
        )
    except IntegrityError:
        existing = OrderPayment.objects.filter(
            org=session.org, idempotency_key=idempotency_key
        ).first()
        if existing:
            return redirect("cashier:payment_wait", public_id=existing.public_id)
        raise

    return redirect("cashier:payment_wait", public_id=payment.public_id)


@login_required
@require_http_methods(["POST"])
def draft_cancel(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    order = get_object_or_404(Order, org=session.org, public_id=public_id)
    try:
        from apps.orders.logic.cancel_draft_order import cancel_draft_order
        cancel_draft_order(order=order, actor=request.user)
    except ValidationError:
        pass
    return redirect("cashier:home")


# ── Order refund ──────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["POST"])
def order_refund(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    order = get_object_or_404(Order, org=session.org, public_id=public_id)
    logger.info(
        "cashier_order_refund_started",
        org_id=str(session.org.public_id),
        order_id=str(order.public_id),
        user_id=str(request.user.id),
    )

    from apps.orders.logic.refund_order import refund_paid_order
    try:
        refund_paid_order(order=order, actor=request.user)

        payment = order.payments.filter(status=OrderPayment.Status.CAPTURED).first()
        if payment and payment.tender == OrderPayment.Tender.CASH:
            CashDrawerMovement.objects.create(
                session=session,
                actor=request.user,
                movement_type=CashDrawerMovement.Type.CASH_OUT,
                amount=payment.amount,
                reason=f"Refund: order {order.public_id}",
            )
        trigger_ekasa_processing(session.org_id)
        logger.info(
            "cashier_order_refund_succeeded",
            org_id=str(session.org.public_id),
            order_id=str(order.public_id),
            tender=payment.tender if payment else "",
        )
    except ValidationError as exc:
        logger.warning(
            "cashier_order_refund_failed",
            org_id=str(session.org.public_id),
            order_id=str(order.public_id),
            error=str(exc),
        )
        request.session[SESSION_REFUND_ERROR] = str(exc)

    return redirect("cashier:home")


# ── Device endpoints (called by physical hardware) ───────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def device_cash_confirm(request: HttpRequest, public_id) -> HttpResponse:
    if not _device_signature_ok(request):
        return _device_auth_failed_response(request)

    payment = get_object_or_404(OrderPayment, public_id=public_id)
    session = (
        CashierSession.objects
        .select_related("org", "terminal")
        .filter(org=payment.org, status=CashierSession.STATUS_OPEN)
        .first()
    )
    if session is None:
        return HttpResponseForbidden("no open session")

    confirm_cash_payment(payment=payment, actor=None, session=session)
    logger.info("cashier_device_cash_confirm_succeeded", payment_id=str(payment.public_id))
    return HttpResponse("ok")


@csrf_exempt
@require_http_methods(["POST"])
def device_card_confirm(request: HttpRequest, public_id) -> HttpResponse:
    if not _device_signature_ok(request):
        return _device_auth_failed_response(request)

    payment = get_object_or_404(OrderPayment, public_id=public_id)
    session = (
        CashierSession.objects
        .select_related("org", "terminal")
        .filter(org=payment.org, status=CashierSession.STATUS_OPEN)
        .first()
    )
    if session is None:
        return HttpResponseForbidden("no open session")

    confirm_card_payment(payment=payment, actor=None, session=session)
    logger.info("cashier_device_card_confirm_succeeded", payment_id=str(payment.public_id))
    return HttpResponse("ok")
