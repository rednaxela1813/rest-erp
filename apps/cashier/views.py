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

import structlog
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from apps.orders.logic.kitchen_tickets import InvalidKitchenTicketStatus, claim_next_ticket, update_ticket_status
from apps.orders.models import Order
from apps.payments.logic.shift import close_shift
from apps.payments.models import CashierSession, OrderPayment
from apps.products.models import Product

from .logic.cart import (
    SESSION_CART,
    SESSION_CHECKOUT_ERROR,
    SESSION_CHECKOUT_IDEMPOTENCY,
    SESSION_ORG_ID,
    SESSION_REFUND_ERROR,
    SESSION_SESSION_ID,
    build_cart_context,
    cart_fingerprint,
    get_cart,
    get_products,
)
from .logic.cart_actions import (
    add_barcode_to_cart,
    add_product_to_cart,
    clear_cart,
    remove_product_from_cart,
    restore_cart,
)
from .logic.checkout_flow import checkout_cart
from .logic.device_confirm import (
    OpenCashierSessionRequired,
    confirm_device_card_payment,
    confirm_device_cash_payment,
)
from .logic.draft_actions import cancel_draft_from_cashier, start_draft_payment
from .logic.home import cashier_home_context
from .logic.kitchen import kitchen_context
from .logic.payment_confirm import confirm_card_payment, confirm_cash_payment
from .logic.payment_flow import build_payment_status_context, refund_order_from_cashier, retry_fiscalization
from .logic.session import cash_drawer_total, get_active_session
from .logic.session_actions import (
    build_session_close_context,
    close_cashier_session,
    open_cashier_session,
    record_cash_in,
)

logger = structlog.get_logger(__name__)
DEVICE_SIGNATURE_MAX_SKEW_SECONDS = 60


# ── Utility ──────────────────────────────────────────────────────────────────


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

    if abs(int(time.time()) - timestamp_value) > DEVICE_SIGNATURE_MAX_SKEW_SECONDS:
        return False

    payload = f"{timestamp}.{request.body.decode('utf-8')}".encode()
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

    result = open_cashier_session(request=request, logger=logger)
    if result.redirect_to_home:
        return redirect("cashier:home")
    return render(request, "cashier/session_open.html", result.context)


@login_required
@require_http_methods(["GET", "POST"])
def session_close(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    if request.method == "POST":
        close_cashier_session(request=request, session=session)
        return redirect("cashier:login")

    context = build_session_close_context(session=session, default_currency=settings.DEFAULT_CURRENCY)
    return render(request, "cashier/session_close.html", context)


@login_required
@require_http_methods(["POST"])
def cash_in(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    record_cash_in(
        session=session,
        actor=request.user,
        raw_amount=request.POST.get("amount", "0"),
        reason=request.POST.get("reason", ""),
    )
    return redirect("cashier:home")


# ── Main page ────────────────────────────────────────────────────────────────


@login_required
@require_http_methods(["GET"])
def cashier_home(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    return render(
        request,
        "cashier/index.html",
        cashier_home_context(
            request_session=request.session,
            session=session,
            cart_error=request.session.pop(SESSION_CHECKOUT_ERROR, ""),
            refund_error=request.session.pop(SESSION_REFUND_ERROR, ""),
        ),
    )


# ── Product catalog ──────────────────────────────────────────────────────────


@login_required
@require_http_methods(["GET"])
def product_list(request: HttpRequest) -> HttpResponse:
    session = get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    query = request.GET.get("q", "").strip()
    return render(
        request,
        "cashier/partials/product_list.html",
        {
            "org": session.org,
            "products": get_products(session.org, query=query),
            "query": query,
            "currency": settings.DEFAULT_CURRENCY,
        },
    )


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
    return render(
        request,
        "cashier/partials/cart.html",
        add_product_to_cart(request_session=request.session, session=session, product=product),
    )


@login_required
@require_http_methods(["POST"])
def cart_add_barcode(request: HttpRequest) -> HttpResponse:
    session = get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    barcode = request.POST.get("barcode", "").strip()
    context = add_barcode_to_cart(request_session=request.session, session=session, barcode=barcode)
    return render(request, "cashier/partials/cart.html", context)


@login_required
@require_http_methods(["POST"])
def cart_remove(request: HttpRequest, product_id: int) -> HttpResponse:
    session = get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    product = get_object_or_404(Product, id=product_id, org=session.org)
    context = remove_product_from_cart(request_session=request.session, session=session, product=product)
    return render(request, "cashier/partials/cart.html", context)


@login_required
@require_http_methods(["POST"])
def cart_clear(request: HttpRequest) -> HttpResponse:
    session = get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    context = clear_cart(request_session=request.session, session=session)
    return render(request, "cashier/partials/cart.html", context)


@login_required
@require_http_methods(["POST"])
def cart_restore(request: HttpRequest) -> HttpResponse:
    session = get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    context = restore_cart(request_session=request.session, session=session, raw_items=request.POST.get("items", "[]"))
    return render(request, "cashier/partials/cart.html", context)


# ── Kitchen ──────────────────────────────────────────────────────────────────


@login_required
@require_http_methods(["GET"])
def kitchen_board(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    return render(
        request,
        "cashier/kitchen.html",
        {
            "org": session.org,
            "session": session,
            **kitchen_context(session.org),
        },
    )


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

    claim_next_ticket(org=session.org)
    return render(request, "cashier/partials/kitchen_panel.html", kitchen_context(session.org))


@login_required
@require_http_methods(["POST"])
def kitchen_update(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    try:
        update_ticket_status(org=session.org, public_id=public_id, status=request.POST.get("status", ""))
    except InvalidKitchenTicketStatus:
        return HttpResponseBadRequest("invalid status")

    return render(request, "cashier/partials/kitchen_panel.html", kitchen_context(session.org))


# ── Checkout ─────────────────────────────────────────────────────────────────


@login_required
@require_http_methods(["POST"])
def checkout(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    result = checkout_cart(request=request, session=session, logger=logger)
    if result.redirect_home or result.payment is None:
        return redirect("cashier:home")
    return redirect("cashier:payment_wait", public_id=result.payment.public_id)


# ── Payment pages ─────────────────────────────────────────────────────────────


@login_required
@require_http_methods(["GET"])
def payment_wait(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    payment = get_object_or_404(OrderPayment, org=session.org, public_id=public_id)
    return render(
        request,
        "cashier/payment_wait.html",
        {
            "org": session.org,
            "session": session,
            "payment": payment,
            "order": payment.order,
            "currency": settings.DEFAULT_CURRENCY,
            "debug": settings.DEBUG,
            "ekasa_enabled": settings.EKASA_ENABLED,
        },
    )


@login_required
@require_http_methods(["GET"])
def payment_status(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    payment = get_object_or_404(OrderPayment, org=session.org, public_id=public_id)
    return render(
        request,
        "cashier/partials/payment_status.html",
        build_payment_status_context(payment=payment, logger=logger),
    )


@login_required
@require_http_methods(["POST"])
def payment_retry_fiscal(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    payment = get_object_or_404(OrderPayment, org=session.org, public_id=public_id)
    if payment.status != OrderPayment.Status.CAPTURED:
        return redirect("cashier:payment_wait", public_id=payment.public_id)

    retry_fiscalization(payment=payment, logger=logger)
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

    payment = start_draft_payment(org=session.org, public_id=public_id, session=session, tender=tender)
    if payment is None:
        return redirect("cashier:home")

    return redirect("cashier:payment_wait", public_id=payment.public_id)


@login_required
@require_http_methods(["POST"])
def draft_cancel(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    cancel_draft_from_cashier(org=session.org, public_id=public_id, actor=request.user)
    return redirect("cashier:home")


# ── Order refund ──────────────────────────────────────────────────────────────


@login_required
@require_http_methods(["POST"])
def order_refund(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    order = get_object_or_404(Order, org=session.org, public_id=public_id)
    refund_order_from_cashier(request=request, order=order, session=session, logger=logger)
    return redirect("cashier:home")


# ── Device endpoints (called by physical hardware) ───────────────────────────


@csrf_exempt
@require_http_methods(["POST"])
def device_cash_confirm(request: HttpRequest, public_id) -> HttpResponse:
    if not _device_signature_ok(request):
        return _device_auth_failed_response(request)

    try:
        confirm_device_cash_payment(public_id=public_id, logger=logger)
    except OpenCashierSessionRequired:
        return HttpResponseForbidden("no open session")

    return HttpResponse("ok")


@csrf_exempt
@require_http_methods(["POST"])
def device_card_confirm(request: HttpRequest, public_id) -> HttpResponse:
    if not _device_signature_ok(request):
        return _device_auth_failed_response(request)

    try:
        confirm_device_card_payment(public_id=public_id, logger=logger)
    except OpenCashierSessionRequired:
        return HttpResponseForbidden("no open session")

    return HttpResponse("ok")
