from __future__ import annotations

from decimal import Decimal, InvalidOperation
import uuid
from typing import Dict, List
import structlog

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import ValidationError

from apps.orders.logic.finalize_paid_order import finalize_paid_order
from apps.orders.logic.refund_order import refund_paid_order
from apps.orders.models import KitchenTicket, Order, OrderItem
from apps.payments.logic.authorize_payment import authorize_payment
from apps.payments.logic.capture_payment import capture_payment
from apps.payments.logic.enqueue_device_commands import _build_fiscal_items, enqueue_payment_commands
from apps.payments.logic.shift import close_shift, shift_report
from apps.payments.models import CashDrawerMovement, CashierSession, DeviceCommand, OrderPayment, Terminal
from apps.products.models import Product
from config.orgs.models import Organization
from apps.accounting.logic.record_sale import record_sale

from apps.recipes.services.check_ingredients import has_enough_ingredients

from .integrations import send_fiscal_receipt, send_receipt_to_printer

SESSION_ORG_ID = "cashier_org_id"
SESSION_SESSION_ID = "cashier_session_id"
SESSION_CART = "cashier_cart"
SESSION_CHECKOUT_IDEMPOTENCY = "cashier_checkout_idempotency"
SESSION_CHECKOUT_ERROR = "cashier_checkout_error"
SESSION_REFUND_ERROR = "cashier_refund_error"

logger = structlog.get_logger(__name__)


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

    qs = (
        Product.objects
        .filter(
            org=org,
            status=Product.STATUS_ACTIVE,
            
            unit__isnull=False,
            tax_rate__isnull=False,
        ).exclude(product_type=Product.PRODUCT_TYPE_INGREDIENT)
        .annotate(
            stock_qty_annotated=Sum(
                "stock_lots__remaining_qty",
                filter=Q(stock_lots__status="active"),
            )
        ).prefetch_related("recipe__ingredients__product__stock_lots")
        .order_by("name")
    )
    if query:
        qs = qs.filter(name__icontains=query)
    # Фильтруем prepared продукты по наличию ингредиентов
    # TODO: вариант Б — перенести проверку в SQL через аннотацию
    result = []
    for product in qs:
        if product.product_type == Product.PRODUCT_TYPE_PREPARED:
            if has_enough_ingredients(product):
                result.append(product)
        else:
            stock_qty = product.stock_qty_annotated or Decimal("0.000")
            if stock_qty > 0:
                result.append(product)
    return result


def _product_checkout_error(product: Product) -> str:
    return (
        f'Product "{product.name}" cannot be sold in cashier until unit and tax rate are set.'
    )


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
    if not cart_items:
        raise ValueError("Cart is empty.")

    # Validate cart item prerequisites before creating the order row.
    # This prevents leaking empty draft orders when a product config is incomplete.
    for item in cart_items:
        product: Product = item["product"]
        if not product.unit or not product.tax_rate:
            raise ValueError("Product is missing unit or tax rate.")

    with transaction.atomic():
        order = Order.objects.create(org=org)
        for item in cart_items:
            product: Product = item["product"]
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


def _trigger_ekasa_processing_for_org(org_id: int) -> None:
    if not settings.EKASA_ENABLED:
        return
    # Lazy import avoids loading Celery task module at import time for simple requests/tests.
    from apps.payments.tasks import process_device_commands_ekasa
    process_device_commands_ekasa.delay(org_id=org_id, limit=50)


def _cash_drawer_total(session: CashierSession) -> Decimal:
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
        session.cash_drawer_start
        + cash_movements["sale_cash"]
        + cash_movements["cash_in"]
        - cash_movements["cash_out"]
    ).quantize(Decimal("0.01"))


def _confirm_cash_payment(*, payment: OrderPayment, actor, session: CashierSession) -> OrderPayment:
    if payment.status == OrderPayment.Status.CAPTURED:
        return payment

    payment.status = OrderPayment.Status.CAPTURED
    payment.captured_at = timezone.now()
    if settings.EKASA_ENABLED:
        payment.fiscal_status = OrderPayment.FiscalStatus.PENDING
        payment.save(update_fields=["status", "captured_at", "fiscal_status", "updated_at"])
    else:
        payment.save(update_fields=["status", "captured_at", "updated_at"])

    if not settings.EKASA_ENABLED:
        try:
            finalize_paid_order(order=payment.order, actor=actor)
           
        except ValidationError as exc:
            payment.status = OrderPayment.Status.FAILED
            payment.failure_reason = str(exc)
            payment.save(update_fields=["status", "failure_reason", "updated_at"])
            return payment
        record_sale(order=payment.order, tender=payment.tender)
    CashDrawerMovement.objects.create(
        session=session,
        actor=actor,
        movement_type=CashDrawerMovement.Type.SALE_CASH,
        amount=payment.amount,
    )
    include_kot = payment.order.kitchen_tickets.exists()
    enqueue_payment_commands(
        payment=payment,
        include_kot=include_kot,
        include_payment_capture=False,
    )
    _trigger_ekasa_processing_for_org(payment.org_id)
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
    active_session = _get_active_session(request)
    if active_session and active_session.status == CashierSession.STATUS_OPEN:
        closing_cash = _cash_drawer_total(active_session)
        close_shift(session=active_session, closing_cash=closing_cash)
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
        logger.info(
            "cashier_session_open_requested",
            user_id=str(request.user.id),
            requested_org_id=selected_org_id,
            requested_terminal_id=selected_terminal_id,
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
                    logger.info(
                        "cashier_session_open_reused_existing",
                        user_id=str(request.user.id),
                        org_id=str(org.public_id),
                        terminal_id=str(terminal.public_id),
                        session_id=str(existing.public_id),
                    )
                    request.session[SESSION_ORG_ID] = str(org.public_id)
                    request.session[SESSION_SESSION_ID] = existing.id
                    request.session.setdefault(SESSION_CART, {})
                    return redirect("cashier:home")
                logger.warning(
                    "cashier_session_open_terminal_busy",
                    user_id=str(request.user.id),
                    org_id=str(org.public_id),
                    terminal_id=str(terminal.public_id),
                    existing_session_id=str(existing.public_id),
                    existing_cashier_id=str(existing.cashier_id),
                )
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
                    terminal_id=str(terminal.public_id),
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
    cash_drawer_total = _cash_drawer_total(session)
    #today = timezone.localdate()
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

    context = {
        "org": org,
        "session": session,
        "products": products,
        "cart_items": items,
        "cart_count": sum(cart.values()) if cart else 0,
        "totals": totals,
        "currency": settings.DEFAULT_CURRENCY,
        "draft_orders": draft_orders,
        "paid_orders": paid_orders,
        "cash_drawer_total": cash_drawer_total,
        "todays_sales_total": todays_sales_total,
        "cart_error": request.session.pop(SESSION_CHECKOUT_ERROR, ""),
        "refund_error": request.session.pop(SESSION_REFUND_ERROR, ""),
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
    error = ""
    if not product.unit or not product.tax_rate:
        error = _product_checkout_error(product)
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
        "last_added": product,
        "cart_error": error,
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
    elif not product.unit or not product.tax_rate:
        error = _product_checkout_error(product)
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

# Добавить в apps/cashier/views.py
# Место вставки: после функции cart_clear (строка ~749)

@login_required
@require_http_methods(["POST"])
def cart_restore(request: HttpRequest) -> HttpResponse:
    """
    Восстанавливает корзину из резервной копии localStorage.

    Принимает JSON-список [{id, qty}, ...] в поле 'items'.
    Валидирует каждый продукт (существование, unit, tax_rate).
    Возвращает обновлённый cart.html partial — как все остальные cart-endpoints.

    Вызывается из JS: htmx.ajax("POST", "/cashier/cart/restore/", ...)
    """
    session = _get_active_session(request)
    if not session:
        return redirect("cashier:session_open")

    raw = request.POST.get("items", "[]")
    try:
        items_data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        items_data = []

    cart = {}
    for entry in items_data:
        try:
            product_id = int(entry.get("id", 0))
            qty = max(1, int(entry.get("qty", 1)))
        except (TypeError, ValueError):
            continue

        # Проверяем что продукт существует и принадлежит этой org
        try:
            product = Product.objects.get(id=product_id, org=session.org)
        except Product.DoesNotExist:
            continue

        # Пропускаем продукты без unit или tax_rate — они не могут быть в чеке
        if not product.unit or not product.tax_rate:
            continue

        cart[str(product_id)] = cart.get(str(product_id), 0) + qty

    request.session[SESSION_CART] = cart
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
        "cart_error": "",
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
    tender = request.POST.get("tender")
    logger.info(
        "cashier_checkout_requested",
        org_id=str(session.org.public_id),
        session_id=str(session.public_id),
        user_id=str(request.user.id),
        tender=tender or "",
        cart_items_count=len(items),
        cart_count=sum(cart.values()) if cart else 0,
    )
    if not items:
        logger.warning(
            "cashier_checkout_empty_cart",
            org_id=str(session.org.public_id),
            session_id=str(session.public_id),
            user_id=str(request.user.id),
        )
        return redirect("cashier:home")

    if tender not in (OrderPayment.Tender.CASH, OrderPayment.Tender.CARD):
        logger.warning(
            "cashier_checkout_invalid_tender",
            org_id=str(session.org.public_id),
            session_id=str(session.public_id),
            user_id=str(request.user.id),
            tender=tender or "",
        )
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
            logger.info(
                "cashier_checkout_reused_existing_payment",
                org_id=str(session.org.public_id),
                session_id=str(session.public_id),
                payment_id=str(existing.public_id),
                idempotency_key=idempotency_key,
            )
            return redirect("cashier:payment_wait", public_id=existing.public_id)
    else:
        idempotency_key = uuid.uuid4().hex
        idem_map[fingerprint] = idempotency_key
        request.session.modified = True

    try:
        order = _build_order_from_cart(org=session.org, cart_items=items)
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
            logger.info(
                "cashier_checkout_integrity_reused_existing_payment",
                org_id=str(session.org.public_id),
                session_id=str(session.public_id),
                payment_id=str(existing.public_id),
                idempotency_key=idempotency_key,
            )
            return redirect("cashier:payment_wait", public_id=existing.public_id)
        raise

    cart.clear()
    request.session.modified = True

    if tender == OrderPayment.Tender.CASH:
        _confirm_cash_payment(payment=payment, actor=request.user, session=session)
    else:
        _confirm_card_payment(payment=payment, actor=request.user, session=session)

    logger.info(
        "cashier_checkout_created_payment",
        org_id=str(session.org.public_id),
        session_id=str(session.public_id),
        order_id=str(order.public_id),
        payment_id=str(payment.public_id),
        tender=tender,
        payment_status=payment.status,
    )
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
        "ekasa_enabled": settings.EKASA_ENABLED,
    }
    return render(request, "cashier/payment_wait.html", context)


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
        has_fiscal_command = DeviceCommand.objects.filter(
            payment=payment,
            command_type__in=fiscal_types,
        ).exists()
        if not has_fiscal_command:
            include_kot = payment.order.kitchen_tickets.exists()
            enqueue_payment_commands(
                payment=payment,
                include_kot=include_kot,
                include_payment_capture=False,
            )

        # Fallback: process fiscal queue inline during status polling.
        # This keeps cashier UI responsive even when Celery is delayed.
        from apps.payments.tasks import process_device_commands_ekasa
        try:
            process_device_commands_ekasa.run(org_id=session.org_id, limit=50)
        except Exception as exc:
            logger.exception(
                "cashier_payment_status_inline_fiscal_failed",
                org_id=str(session.org.public_id),
                session_id=str(session.public_id),
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
    context = {
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
    }
    return render(request, "cashier/partials/payment_status.html", context)


@login_required
@require_http_methods(["POST"])
def payment_retry_fiscal(request: HttpRequest, public_id) -> HttpResponse:
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    payment = get_object_or_404(OrderPayment, org=session.org, public_id=public_id)
    if payment.status != OrderPayment.Status.CAPTURED:
        logger.warning(
            "cashier_payment_retry_fiscal_invalid_status",
            org_id=str(session.org.public_id),
            session_id=str(session.public_id),
            payment_id=str(payment.public_id),
            payment_status=payment.status,
        )
        return redirect("cashier:payment_wait", public_id=payment.public_id)

    logger.info(
        "cashier_payment_retry_fiscal_started",
        org_id=str(session.org.public_id),
        session_id=str(session.public_id),
        payment_id=str(payment.public_id),
        order_id=str(payment.order.public_id),
    )
    sale_command = (
        DeviceCommand.objects
        .filter(payment=payment, command_type=DeviceCommand.Type.FISCALIZE_SALE)
        .order_by("-created_at")
        .first()
    )
    if sale_command is None:
        include_kot = payment.order.kitchen_tickets.exists()
        enqueue_payment_commands(
            payment=payment,
            include_kot=include_kot,
            include_payment_capture=False,
        )
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
            update_fields=[
                "payload",
                "status",
                "retries",
                "last_error",
                "next_attempt_at",
                "updated_at",
            ]
        )

    payment.fiscal_status = OrderPayment.FiscalStatus.PENDING
    payment.failure_reason = ""
    payment.save(update_fields=["fiscal_status", "failure_reason", "updated_at"])
    _trigger_ekasa_processing_for_org(payment.org_id)
    logger.info(
        "cashier_payment_retry_fiscal_succeeded",
        org_id=str(session.org.public_id),
        session_id=str(session.public_id),
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
        payment = _create_payment(
            order=order,
            session=session,
            tender=tender,
            idempotency_key=idempotency_key,
        )
    except IntegrityError:
        existing = OrderPayment.objects.filter(org=session.org, idempotency_key=idempotency_key).first()
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
        session_id=str(session.public_id),
        order_id=str(order.public_id),
        user_id=str(request.user.id),
    )
    try:
        refund_paid_order(order=order, actor=request.user)

        # For cash refunds: record cash leaving the drawer.
        # Card refunds have no physical drawer movement — no terminal integration.
        payment = order.payments.filter(status=OrderPayment.Status.CAPTURED).first()
        if payment and payment.tender == OrderPayment.Tender.CASH:
            CashDrawerMovement.objects.create(
                session=session,
                actor=request.user,
                movement_type=CashDrawerMovement.Type.CASH_OUT,
                amount=payment.amount,
                reason=f"Refund: order {order.public_id}",
            )

        _trigger_ekasa_processing_for_org(session.org_id)
        logger.info(
            "cashier_order_refund_succeeded",
            org_id=str(session.org.public_id),
            session_id=str(session.public_id),
            order_id=str(order.public_id),
            user_id=str(request.user.id),
            tender=payment.tender if payment else "",
        )
    except ValidationError as exc:
        logger.warning(
            "cashier_order_refund_failed",
            org_id=str(session.org.public_id),
            session_id=str(session.public_id),
            order_id=str(order.public_id),
            user_id=str(request.user.id),
            error=str(exc),
        )
        request.session[SESSION_REFUND_ERROR] = str(exc)

    return redirect("cashier:home")


@csrf_exempt
@require_http_methods(["POST"])
def device_cash_confirm(request: HttpRequest, public_id) -> HttpResponse:
    if not _device_token_ok(request):
        logger.warning(
            "cashier_device_cash_confirm_invalid_token",
            payment_id=str(public_id),
        )
        return HttpResponseForbidden("invalid device token")

    payment = get_object_or_404(OrderPayment, public_id=public_id)
    session = (
        CashierSession.objects
        .select_related("org", "terminal")
        .filter(org=payment.org, status=CashierSession.STATUS_OPEN)
        .first()
    )
    if session is None:
        logger.warning(
            "cashier_device_cash_confirm_no_open_session",
            payment_id=str(payment.public_id),
            org_id=str(payment.org.public_id),
        )
        return HttpResponseForbidden("no open session")

    _confirm_cash_payment(payment=payment, actor=None, session=session)
    logger.info(
        "cashier_device_cash_confirm_succeeded",
        payment_id=str(payment.public_id),
        order_id=str(payment.order.public_id),
        session_id=str(session.public_id),
    )
    return HttpResponse("ok")


@csrf_exempt
@require_http_methods(["POST"])
def device_card_confirm(request: HttpRequest, public_id) -> HttpResponse:
    if not _device_token_ok(request):
        logger.warning(
            "cashier_device_card_confirm_invalid_token",
            payment_id=str(public_id),
        )
        return HttpResponseForbidden("invalid device token")

    payment = get_object_or_404(OrderPayment, public_id=public_id)
    session = (
        CashierSession.objects
        .select_related("org", "terminal")
        .filter(org=payment.org, status=CashierSession.STATUS_OPEN)
        .first()
    )
    if session is None:
        logger.warning(
            "cashier_device_card_confirm_no_open_session",
            payment_id=str(payment.public_id),
            org_id=str(payment.org.public_id),
        )
        return HttpResponseForbidden("no open session")

    _confirm_card_payment(payment=payment, actor=None, session=session)
    logger.info(
        "cashier_device_card_confirm_succeeded",
        payment_id=str(payment.public_id),
        order_id=str(payment.order.public_id),
        session_id=str(session.public_id),
    )
    return HttpResponse("ok")


@login_required
@require_http_methods(["GET", "POST"])
def session_close(request: HttpRequest) -> HttpResponse:
    """
    Z-отчёт и закрытие смены.

    Двухшаговый процесс — кассир сначала видит итоги смены (GET),
    затем явно подтверждает закрытие (POST).

    Это защищает от случайного нажатия «Log out» в середине рабочего дня
    и даёт возможность распечатать отчёт перед закрытием.

    GET  — формирует отчёт по смене и показывает страницу подтверждения.
    POST — фиксирует остаток в ящике, закрывает смену, разлогинивает кассира.
    """
    # Проверяем что есть активная сессия.
    # _require_session_or_redirect вернёт HttpResponse-редирект если сессии нет,
    # поэтому проверяем тип возвращаемого значения.
    session = _require_session_or_redirect(request)
    if isinstance(session, HttpResponse):
        return session

    # Строим отчёт по текущей смене.
    # shift_report агрегирует все захваченные платежи за период смены:
    # итоги по тендеру (cash/card), итоги по ставкам НДС, общий оборот.
    report = shift_report(session=session)

    # Считаем текущий остаток в кассовом ящике.
    # Формула: opening_float + все cash_in + все sale_cash - все cash_out.
    # Это число используется как closing_cash при закрытии смены.
    cash_drawer_total = _cash_drawer_total(session)

    if request.method == "POST":
        # Фиксируем closing_cash и переводим сессию в статус CLOSED.
        # После этого сессию нельзя переоткрыть — только создать новую.
        close_shift(session=session, closing_cash=cash_drawer_total)

        # Разлогиниваем пользователя из Django-сессии.
        logout(request)

        # Явно чистим кассовые ключи из сессии.
        # logout() очищает всю сессию, но мы делаем это явно для читаемости
        # и на случай если Django изменит поведение logout() в будущих версиях.
        request.session.pop(SESSION_ORG_ID, None)
        request.session.pop(SESSION_SESSION_ID, None)
        request.session.pop(SESSION_CART, None)

        return redirect("cashier:login")

    # GET: показываем страницу с Z-отчётом для подтверждения.
    return render(
        request,
        "cashier/session_close.html",
        {
            "session": session,
            "org": session.org,
            # report содержит: payments_total, tax_total, by_tender, by_tax_rate
            "report": report,
            # Остаток в ящике — будет записан как closing_cash при POST
            "cash_drawer_total": cash_drawer_total,
            "currency": settings.DEFAULT_CURRENCY,
        },
    )