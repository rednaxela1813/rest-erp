from __future__ import annotations

from decimal import Decimal, InvalidOperation
import uuid
from typing import Dict, List

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from apps.orders.logic.finalize_paid_order import finalize_paid_order
from apps.orders.models import KitchenTicket, Order, OrderItem
from apps.payments.logic.authorize_payment import authorize_payment
from apps.payments.logic.capture_payment import capture_payment
from apps.payments.models import CashDrawerMovement, CashierSession, OrderPayment, Terminal
from apps.products.models import Product
from config.orgs.models import Organization

from .integrations import send_fiscal_receipt, send_receipt_to_printer

SESSION_ORG_ID = "cashier_org_id"
SESSION_SESSION_ID = "cashier_session_id"
SESSION_CART = "cashier_cart"
SESSION_CHECKOUT_IDEMPOTENCY = "cashier_checkout_idempotency"


def _parse_amount(raw_value: str) -> Decimal:
    try:
        return Decimal(raw_value).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        return Decimal("0.00")


def _get_active_org(request: HttpRequest) -> Organization | None:
    org_id = request.session.get(SESSION_ORG_ID)
    if not org_id:
        return None
    return Organization.objects.filter(public_id=org_id, members__user=request.user).first()


def _get_active_session(request: HttpRequest) -> CashierSession | None:
    session_id = request.session.get(SESSION_SESSION_ID)
    if not session_id:
        return None
    session = (
        CashierSession.objects
        .select_related("org", "terminal")
        .filter(pk=session_id, cashier=request.user, status=CashierSession.STATUS_OPEN)
        .first()
    )
    if session is None:
        request.session.pop(SESSION_SESSION_ID, None)
        request.session.pop(SESSION_ORG_ID, None)
    return session


def _require_session_or_redirect(request: HttpRequest) -> CashierSession | HttpResponse:
    session = _get_active_session(request)
    if session is None:
        return redirect("cashier:session_open")
    return session


def _get_cart(session) -> Dict[str, int]:
    cart = session.get(SESSION_CART)
    if not isinstance(cart, dict):
        cart = {}
        session[SESSION_CART] = cart
    return cart


def _reset_checkout_idempotency(session) -> None:
    session.pop(SESSION_CHECKOUT_IDEMPOTENCY, None)


def _cart_fingerprint(*, cart: Dict[str, int], tender: str) -> str:
    if not cart:
        return ""
    items = [f"{product_id}:{qty}" for product_id, qty in sorted(cart.items())]
    return f"{tender}|" + "|".join(items)


def _get_products(org: Organization | None, query: str = ""):
    if not org:
        return Product.objects.none()

    qs = Product.objects.filter(org=org, status=Product.STATUS_ACTIVE).order_by("name")
    if query:
        qs = qs.filter(name__icontains=query)
    return qs


def _get_product_unit_price(product: Product) -> Decimal:
    if product.is_bundle:
        return product.recompute_bundle_price()
    return product.unit_price


def _tax_included_amount(amount: Decimal, rate: Decimal) -> Decimal:
    if rate <= 0:
        return Decimal("0.00")
    divisor = Decimal("1.00") + (rate / Decimal("100"))
    if divisor == 0:
        return Decimal("0.00")
    return (amount - (amount / divisor)).quantize(Decimal("0.01"))


def _cart_items(cart: Dict[str, int], org: Organization | None) -> List[dict]:
    if not cart or not org:
        return []

    product_ids = [int(pid) for pid in cart.keys() if pid.isdigit()]
    products_by_id = {
        str(product.id): product
        for product in Product.objects.filter(org=org, id__in=product_ids).prefetch_related(
            "bundle_items__component"
        )
    }

    items: List[dict] = []
    for product_id, qty in cart.items():
        product = products_by_id.get(product_id)
        if not product:
            continue
        unit_price = _get_product_unit_price(product)
        line_total = (unit_price * Decimal(qty)).quantize(Decimal("0.01"))
        tax_rate = product.tax_rate.rate if product.tax_rate else Decimal("0.00")
        tax_amount = _tax_included_amount(line_total, tax_rate)
        items.append(
            {
                "product": product,
                "qty": qty,
                "line_total": line_total,
                "unit_price": unit_price,
                "tax_amount": tax_amount,
            }
        )
    return items


def _cart_totals(items: List[dict]) -> dict:
    subtotal = sum((item["line_total"] for item in items), Decimal("0.00"))
    tax_total = sum((item["tax_amount"] for item in items), Decimal("0.00"))
    return {
        "subtotal": subtotal.quantize(Decimal("0.01")),
        "total": subtotal.quantize(Decimal("0.01")),
        "tax_total": tax_total.quantize(Decimal("0.01")),
    }


def _build_order_from_cart(*, org: Organization, cart_items: List[dict]) -> Order:
    order = Order.objects.create(org=org)
    for item in cart_items:
        product: Product = item["product"]
        if not product.unit or not product.tax_rate:
            raise ValueError("Product is missing unit or tax rate.")
        unit_price = item.get("unit_price") or _get_product_unit_price(product)
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            qty=Decimal(item["qty"]),
            unit=product.unit,
            unit_price=unit_price,
            tax_rate=product.tax_rate,
        )
    order.recompute_totals()
    order.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])
    return order


def _kitchen_context(org: Organization) -> dict:
    pending = (
        KitchenTicket.objects
        .filter(org=org, status=KitchenTicket.Status.PENDING)
        .select_related("order", "product")
        .order_by("created_at", "id")
    )
    in_progress = (
        KitchenTicket.objects
        .filter(org=org, status=KitchenTicket.Status.IN_PROGRESS)
        .select_related("order", "product")
        .order_by("created_at", "id")
    )
    return {
        "pending_tickets": pending,
        "in_progress_tickets": in_progress,
    }


def _create_payment(
    *,
    order: Order,
    session: CashierSession,
    tender: str,
    idempotency_key: str | None = None,
) -> OrderPayment:
    payment = OrderPayment.objects.create(
        org=order.org,
        order=order,
        terminal=session.terminal,
        tender=tender,
        status=OrderPayment.Status.PENDING,
        amount=order.total,
        currency=settings.DEFAULT_CURRENCY,
        provider="manual",
        idempotency_key=idempotency_key,
    )
    return payment


def _send_receipts(*, order: Order, payment: OrderPayment, session: CashierSession) -> None:
    send_receipt_to_printer(order=order, payment=payment, session=session)
    send_fiscal_receipt(order=order, payment=payment, session=session)


def _confirm_cash_payment(*, payment: OrderPayment, actor, session: CashierSession) -> OrderPayment:
    if payment.status == OrderPayment.Status.CAPTURED:
        return payment

    payment.status = OrderPayment.Status.CAPTURED
    payment.captured_at = timezone.now()
    payment.save(update_fields=["status", "captured_at", "updated_at"])

    try:
        finalize_paid_order(order=payment.order, actor=actor)
    except ValidationError as exc:
        payment.status = OrderPayment.Status.FAILED
        payment.failure_reason = str(exc)
        payment.save(update_fields=["status", "failure_reason", "updated_at"])
        return payment

    CashDrawerMovement.objects.create(
        session=session,
        actor=actor,
        movement_type=CashDrawerMovement.Type.SALE_CASH,
        amount=payment.amount,
    )
    _send_receipts(order=payment.order, payment=payment, session=session)
    return payment


def _confirm_card_payment(*, payment: OrderPayment, actor, session: CashierSession) -> OrderPayment:
    if payment.status == OrderPayment.Status.CAPTURED:
        return payment

    if payment.status == OrderPayment.Status.PENDING:
        try:
            authorize_payment(payment=payment, actor=actor, terminal=session.terminal, session=session)
            payment.refresh_from_db()
        except ValidationError as exc:
            payment.status = OrderPayment.Status.FAILED
            payment.failure_reason = str(exc)
            payment.save(update_fields=["status", "failure_reason", "updated_at"])
            return payment

    if payment.status == OrderPayment.Status.AUTHORIZED:
        try:
            capture_payment(payment=payment, actor=actor)
            payment.refresh_from_db()
        except ValidationError as exc:
            payment.status = OrderPayment.Status.FAILED
            payment.failure_reason = str(exc)
            payment.save(update_fields=["status", "failure_reason", "updated_at"])
            return payment

    _send_receipts(order=payment.order, payment=payment, session=session)
    return payment


def _device_token_ok(request: HttpRequest) -> bool:
    token = settings.CASHIER_DEVICE_TOKEN
    if not token:
        return True
    return request.headers.get("X-DEVICE-TOKEN") == token


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
    logout(request)
    request.session.pop(SESSION_ORG_ID, None)
    request.session.pop(SESSION_SESSION_ID, None)
    request.session.pop(SESSION_CART, None)
    return redirect("cashier:login")


@login_required
@require_http_methods(["GET", "POST"])
def session_open(request: HttpRequest) -> HttpResponse:
    active_session = _get_active_session(request)
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


@login_required
@require_http_methods(["GET"])
def cashier_home(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    org = session.org
    products = _get_products(org)
    cart = _get_cart(request.session)
    items = _cart_items(cart, org)
    totals = _cart_totals(items)

    context = {
        "org": org,
        "session": session,
        "products": products,
        "cart_items": items,
        "cart_count": sum(cart.values()) if cart else 0,
        "totals": totals,
        "currency": settings.DEFAULT_CURRENCY,
    }
    return render(request, "cashier/index.html", context)


@login_required
@require_http_methods(["GET"])
def product_list(request: HttpRequest) -> HttpResponse:
    session = _get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    query = request.GET.get("q", "").strip()
    context = {
        "org": session.org,
        "products": _get_products(session.org, query=query),
        "query": query,
        "currency": settings.DEFAULT_CURRENCY,
    }
    return render(request, "cashier/partials/product_list.html", context)


@login_required
@require_http_methods(["GET"])
def cart_panel(request: HttpRequest) -> HttpResponse:
    session = _get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    cart = _get_cart(request.session)
    items = _cart_items(cart, session.org)
    totals = _cart_totals(items)
    context = {
        "org": session.org,
        "cart_items": items,
        "cart_count": sum(cart.values()) if cart else 0,
        "totals": totals,
        "currency": settings.DEFAULT_CURRENCY,
    }
    return render(request, "cashier/partials/cart.html", context)


@login_required
@require_http_methods(["POST"])
def cart_add(request: HttpRequest, product_id: int) -> HttpResponse:
    session = _get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    product = get_object_or_404(Product, id=product_id, org=session.org)
    cart = _get_cart(request.session)
    key = str(product.id)
    cart[key] = cart.get(key, 0) + 1
    _reset_checkout_idempotency(request.session)
    request.session.modified = True

    items = _cart_items(cart, session.org)
    totals = _cart_totals(items)
    context = {
        "org": session.org,
        "cart_items": items,
        "cart_count": sum(cart.values()) if cart else 0,
        "totals": totals,
        "currency": settings.DEFAULT_CURRENCY,
        "last_added": product,
    }
    return render(request, "cashier/partials/cart.html", context)


@login_required
@require_http_methods(["POST"])
def cart_add_barcode(request: HttpRequest) -> HttpResponse:
    session = _get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    barcode = request.POST.get("barcode", "").strip()
    product = Product.objects.filter(org=session.org, barcode=barcode).first()
    cart = _get_cart(request.session)
    error = ""

    if not barcode:
        error = "Barcode is required."
    elif not product:
        error = f"Product with barcode {barcode} not found."
    else:
        key = str(product.id)
        cart[key] = cart.get(key, 0) + 1
        _reset_checkout_idempotency(request.session)
        request.session.modified = True

    items = _cart_items(cart, session.org)
    totals = _cart_totals(items)
    context = {
        "org": session.org,
        "cart_items": items,
        "cart_count": sum(cart.values()) if cart else 0,
        "totals": totals,
        "currency": settings.DEFAULT_CURRENCY,
        "cart_error": error,
    }
    return render(request, "cashier/partials/cart.html", context)


@login_required
@require_http_methods(["POST"])
def cart_remove(request: HttpRequest, product_id: int) -> HttpResponse:
    session = _get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    product = get_object_or_404(Product, id=product_id, org=session.org)
    cart = _get_cart(request.session)
    key = str(product.id)
    if key in cart:
        new_qty = cart[key] - 1
        if new_qty <= 0:
            cart.pop(key, None)
        else:
            cart[key] = new_qty
        _reset_checkout_idempotency(request.session)
        request.session.modified = True

    items = _cart_items(cart, session.org)
    totals = _cart_totals(items)
    context = {
        "org": session.org,
        "cart_items": items,
        "cart_count": sum(cart.values()) if cart else 0,
        "totals": totals,
        "currency": settings.DEFAULT_CURRENCY,
    }
    return render(request, "cashier/partials/cart.html", context)


@login_required
@require_http_methods(["POST"])
def cart_clear(request: HttpRequest) -> HttpResponse:
    session = _get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    cart = _get_cart(request.session)
    cart.clear()
    _reset_checkout_idempotency(request.session)
    request.session.modified = True
    context = {
        "org": session.org,
        "cart_items": [],
        "cart_count": 0,
        "totals": {"subtotal": Decimal("0.00"), "total": Decimal("0.00")},
        "currency": settings.DEFAULT_CURRENCY,
    }
    return render(request, "cashier/partials/cart.html", context)


@login_required
@require_http_methods(["GET"])
def kitchen_board(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    context = {
        "org": session.org,
        "session": session,
        **_kitchen_context(session.org),
    }
    return render(request, "cashier/kitchen.html", context)


@login_required
@require_http_methods(["GET"])
def kitchen_panel(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    context = _kitchen_context(session.org)
    return render(request, "cashier/partials/kitchen_panel.html", context)


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

    context = _kitchen_context(session.org)
    return render(request, "cashier/partials/kitchen_panel.html", context)


@login_required
@require_http_methods(["POST"])
def kitchen_update(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    status_value = request.POST.get("status")
    allowed = {
        KitchenTicket.Status.IN_PROGRESS,
        KitchenTicket.Status.DONE,
        KitchenTicket.Status.CANCELLED,
    }
    if status_value not in allowed:
        return HttpResponseBadRequest("invalid status")

    ticket = get_object_or_404(KitchenTicket, org=session.org, public_id=public_id)
    ticket.status = status_value
    ticket.save(update_fields=["status", "updated_at"])

    context = _kitchen_context(session.org)
    return render(request, "cashier/partials/kitchen_panel.html", context)


@login_required
@require_http_methods(["POST"])
def checkout(request: HttpRequest) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    cart = _get_cart(request.session)
    items = _cart_items(cart, session.org)
    if not items:
        return redirect("cashier:home")

    tender = request.POST.get("tender")
    if tender not in (OrderPayment.Tender.CASH, OrderPayment.Tender.CARD):
        return redirect("cashier:home")

    fingerprint = _cart_fingerprint(cart=cart, tender=tender)
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
        order = _build_order_from_cart(org=session.org, cart_items=items)
    except ValueError:
        return redirect("cashier:home")

    try:
        payment = _create_payment(
            order=order,
            session=session,
            tender=tender,
            idempotency_key=idempotency_key,
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

    return redirect("cashier:payment_wait", public_id=payment.public_id)


@login_required
@require_http_methods(["GET"])
def payment_wait(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    payment = get_object_or_404(OrderPayment, org=session.org, public_id=public_id)
    context = {
        "org": session.org,
        "session": session,
        "payment": payment,
        "order": payment.order,
        "currency": settings.DEFAULT_CURRENCY,
        "debug": settings.DEBUG,
    }
    return render(request, "cashier/payment_wait.html", context)


@login_required
@require_http_methods(["GET"])
def payment_status(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    payment = get_object_or_404(OrderPayment, org=session.org, public_id=public_id)
    context = {
        "payment": payment,
        "order": payment.order,
        "currency": settings.DEFAULT_CURRENCY,
    }
    return render(request, "cashier/partials/payment_status.html", context)


@login_required
@require_http_methods(["POST"])
def payment_confirm_cash(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    payment = get_object_or_404(OrderPayment, org=session.org, public_id=public_id)
    _confirm_cash_payment(payment=payment, actor=request.user, session=session)
    return redirect("cashier:payment_wait", public_id=payment.public_id)


@login_required
@require_http_methods(["POST"])
def payment_confirm_card(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    payment = get_object_or_404(OrderPayment, org=session.org, public_id=public_id)
    _confirm_card_payment(payment=payment, actor=request.user, session=session)
    return redirect("cashier:payment_wait", public_id=payment.public_id)


@csrf_exempt
@require_http_methods(["POST"])
def device_cash_confirm(request: HttpRequest, public_id) -> HttpResponse:
    if not _device_token_ok(request):
        return HttpResponseForbidden("invalid device token")

    payment = get_object_or_404(OrderPayment, public_id=public_id)
    session = (
        CashierSession.objects
        .select_related("org", "terminal")
        .filter(org=payment.org, status=CashierSession.STATUS_OPEN)
        .first()
    )
    if session is None:
        return HttpResponseForbidden("no open session")

    _confirm_cash_payment(payment=payment, actor=None, session=session)
    return HttpResponse("ok")


@csrf_exempt
@require_http_methods(["POST"])
def device_card_confirm(request: HttpRequest, public_id) -> HttpResponse:
    if not _device_token_ok(request):
        return HttpResponseForbidden("invalid device token")

    payment = get_object_or_404(OrderPayment, public_id=public_id)
    session = (
        CashierSession.objects
        .select_related("org", "terminal")
        .filter(org=payment.org, status=CashierSession.STATUS_OPEN)
        .first()
    )
    if session is None:
        return HttpResponseForbidden("no open session")

    _confirm_card_payment(payment=payment, actor=None, session=session)
    return HttpResponse("ok")
