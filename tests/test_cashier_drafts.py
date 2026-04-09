from decimal import Decimal

import pytest
from django.utils import timezone

from apps.cashier import views as cashier_views
from apps.orders.models import Order, OrderItem
from apps.payments.models import CashDrawerMovement, CashierSession, DeviceCommand, OrderPayment, Terminal
from apps.products.models import Product, TaxRate, Unit
from config.orgs.models import OrganizationMember


def _prepare_cashier_session(*, client, org, user) -> CashierSession:
    terminal = Terminal.objects.create(org=org, name="POS 1", code="pos-1")
    session = CashierSession.objects.create(
        org=org,
        terminal=terminal,
        cashier=user,
        cash_drawer_start=Decimal("0.00"),
    )
    session_data = client.session
    session_data[cashier_views.SESSION_ORG_ID] = str(org.public_id)
    session_data[cashier_views.SESSION_SESSION_ID] = session.id
    session_data[cashier_views.SESSION_CART] = {}
    session_data.save()
    return session


def _prepare_product(*, org) -> Product:
    from apps.inventory.services.receive_stock import receive_stock
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    product = Product.objects.create(
        org=org,
        name="Burger",
        unit=unit,
        tax_rate=tax_rate,
        unit_price=Decimal("5.00"),
    )
    receive_stock(org=org, product=product, initial_qty=Decimal("10.000"), unit_cost=Decimal("1.00"), label_code="LOT-BURGER")
    return product


@pytest.mark.django_db
def test_cashier_home_shows_drafts(client, user_factory, org_factory):
    user = user_factory(email="cashier@example.com")
    org = org_factory(name="Cashier Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    _prepare_cashier_session(client=client, org=org, user=user)

    product = _prepare_product(org=org)
    order = Order.objects.create(org=org, status=Order.STATUS_DRAFT)
    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("1.000"),
        unit=product.unit,
        unit_price=product.unit_price,
        tax_rate=product.tax_rate,
    )
    order.recompute_totals()
    order.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])

    resp = client.get("/cashier/")
    assert resp.status_code == 200
    assert b"Draft Orders" in resp.content
    assert str(order.public_id).encode() in resp.content


@pytest.mark.django_db
def test_draft_pay_creates_payment(client, user_factory, org_factory):
    user = user_factory(email="cashier@example.com")
    org = org_factory(name="Cashier Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    _prepare_cashier_session(client=client, org=org, user=user)

    product = _prepare_product(org=org)
    order = Order.objects.create(org=org, status=Order.STATUS_DRAFT)
    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("1.000"),
        unit=product.unit,
        unit_price=product.unit_price,
        tax_rate=product.tax_rate,
    )
    order.recompute_totals()
    order.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])

    resp = client.post(f"/cashier/drafts/{order.public_id}/pay/card/")
    assert resp.status_code == 302
    payment = OrderPayment.objects.get(order=order)
    assert payment.tender == OrderPayment.Tender.CARD


@pytest.mark.django_db
def test_draft_cancel_changes_status(client, user_factory, org_factory):
    user = user_factory(email="cashier@example.com")
    org = org_factory(name="Cashier Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    _prepare_cashier_session(client=client, org=org, user=user)

    order = Order.objects.create(org=org, status=Order.STATUS_DRAFT)
    resp = client.post(f"/cashier/drafts/{order.public_id}/cancel/")
    assert resp.status_code == 302
    order.refresh_from_db()
    assert order.status == Order.STATUS_CANCELLED


@pytest.mark.django_db
def test_cashier_home_shows_cash_drawer_total(client, user_factory, org_factory):
    user = user_factory(email="cashier@example.com")
    org = org_factory(name="Cashier Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    session = _prepare_cashier_session(client=client, org=org, user=user)
    session.cash_drawer_start = Decimal("10.00")
    session.save(update_fields=["cash_drawer_start", "updated_at"])

    CashDrawerMovement.objects.create(
        session=session,
        actor=user,
        movement_type=CashDrawerMovement.Type.SALE_CASH,
        amount=Decimal("15.50"),
    )
    CashDrawerMovement.objects.create(
        session=session,
        actor=user,
        movement_type=CashDrawerMovement.Type.CASH_IN,
        amount=Decimal("2.00"),
    )
    CashDrawerMovement.objects.create(
        session=session,
        actor=user,
        movement_type=CashDrawerMovement.Type.CASH_OUT,
        amount=Decimal("1.00"),
    )

    resp = client.get("/cashier/")
    assert resp.status_code == 200
    assert b"Cash drawer 26.50" in resp.content


@pytest.mark.django_db
def test_cashier_home_shows_shift_sales_total(client, user_factory, org_factory):
    user = user_factory(email="cashier@example.com")
    org = org_factory(name="Cashier Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    session = _prepare_cashier_session(client=client, org=org, user=user)

    order_1 = Order.objects.create(org=org)
    order_2 = Order.objects.create(org=org)
    order_3 = Order.objects.create(org=org)

    # Считается: наличные в текущей смене
    OrderPayment.objects.create(
        org=org, order=order_1, terminal=session.terminal,
        tender=OrderPayment.Tender.CASH,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("10.00"), currency="EUR", provider="manual",
        captured_at=timezone.now(),
    )
    # Считается: карта в текущей смене
    OrderPayment.objects.create(
        org=org, order=order_2, terminal=session.terminal,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("7.50"), currency="EUR", provider="manual",
        captured_at=timezone.now(),
    )
    # Не считается: платёж ДО открытия смены
    OrderPayment.objects.create(
        org=org, order=order_3, terminal=session.terminal,
        tender=OrderPayment.Tender.CASH,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("50.00"), currency="EUR", provider="manual",
        captured_at=session.opened_at - timezone.timedelta(hours=1),
    )

    resp = client.get("/cashier/")
    assert resp.status_code == 200
    assert b"Shift sales 17.50" in resp.content

@pytest.mark.django_db
def test_logout_closes_open_shift_with_current_cash(client, user_factory, org_factory):
    user = user_factory(email="cashier@example.com")
    org = org_factory(name="Cashier Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    session = _prepare_cashier_session(client=client, org=org, user=user)
    session.cash_drawer_start = Decimal("100.00")
    session.save(update_fields=["cash_drawer_start", "updated_at"])

    CashDrawerMovement.objects.create(
        session=session,
        actor=user,
        movement_type=CashDrawerMovement.Type.SALE_CASH,
        amount=Decimal("20.00"),
    )
    CashDrawerMovement.objects.create(
        session=session,
        actor=user,
        movement_type=CashDrawerMovement.Type.CASH_IN,
        amount=Decimal("10.00"),
    )
    CashDrawerMovement.objects.create(
        session=session,
        actor=user,
        movement_type=CashDrawerMovement.Type.CASH_OUT,
        amount=Decimal("5.00"),
    )

    resp = client.post("/cashier/logout/")
    assert resp.status_code == 302

    session.refresh_from_db()
    assert session.status == CashierSession.STATUS_CLOSED
    assert session.cash_drawer_end == Decimal("125.00")


@pytest.mark.django_db
def test_cashier_refund_paid_order_enqueues_refund_command(client, user_factory, org_factory, settings):
    settings.EKASA_ENABLED = False
    user = user_factory(email="cashier@example.com")
    org = org_factory(name="Cashier Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    _prepare_cashier_session(client=client, org=org, user=user)

    product = _prepare_product(org=org)
    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 1}
    session_data.save()

    checkout_resp = client.post("/cashier/checkout/", data={"tender": "cash"})
    assert checkout_resp.status_code == 302
    payment = OrderPayment.objects.get(org=org)
    order = payment.order
    assert order.status == Order.STATUS_PAID

    # Simulate existing sale receipt reference required for refund payload.
    from apps.payments.models import FiscalReceipt
    FiscalReceipt.objects.get_or_create(
        payment=payment,
        receipt_type=FiscalReceipt.Type.SALE,
        defaults={
            "org": org,
            "order": order,
            "total": payment.amount,
            "tax_total": order.tax_total,
            "currency": payment.currency,
            "raw_payload": {"receipt_id": "ekasa-sale-1"},
        },
    )

    refund_resp = client.post(f"/cashier/orders/{order.public_id}/refund/")
    assert refund_resp.status_code == 302
    order.refresh_from_db()
    assert order.status == Order.STATUS_CANCELLED

    refund_cmd = DeviceCommand.objects.filter(
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_REFUND,
    ).first()
    assert refund_cmd is not None


@pytest.mark.django_db
def test_session_open_requires_valid_org_and_terminal_selection(client, user_factory, org_factory):
    user = user_factory(email="cashier@example.com")
    org = org_factory(name="Cashier Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)

    resp = client.post(
        "/cashier/session/open/",
        data={"org_id": str(org.public_id), "terminal_id": "999999", "opening_cash": "10.00"},
    )

    assert resp.status_code == 200
    assert b"Select organization and terminal." in resp.content


@pytest.mark.django_db
def test_session_open_rejects_terminal_with_other_cashier_session(client, user_factory, org_factory):
    user_1 = user_factory(email="cashier1@example.com")
    user_2 = user_factory(email="cashier2@example.com")
    org = org_factory(name="Cashier Org")
    OrganizationMember.objects.create(org=org, user=user_1, role="member")
    OrganizationMember.objects.create(org=org, user=user_2, role="member")
    terminal = Terminal.objects.create(org=org, name="POS 1", code="pos-1", status=Terminal.STATUS_ACTIVE)
    CashierSession.objects.create(
        org=org,
        terminal=terminal,
        cashier=user_1,
        cash_drawer_start=Decimal("0.00"),
    )

    client.force_login(user_2)

    resp = client.post(
        "/cashier/session/open/",
        data={"org_id": str(org.public_id), "terminal_id": str(terminal.id), "opening_cash": "10.00"},
    )

    assert resp.status_code == 200
    assert b"Terminal already has an open session." in resp.content


@pytest.mark.django_db
def test_device_cash_confirm_rejects_invalid_device_token(client, user_factory, org_factory, settings):
    user = user_factory(email="cashier@example.com")
    org = org_factory(name="Cashier Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    session = _prepare_cashier_session(client=client, org=org, user=user)
    product = _prepare_product(org=org)
    order = Order.objects.create(org=org, status=Order.STATUS_DRAFT)
    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("1.000"),
        unit=product.unit,
        unit_price=product.unit_price,
        tax_rate=product.tax_rate,
    )
    order.recompute_totals()
    order.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        terminal=session.terminal,
        tender=OrderPayment.Tender.CASH,
        status=OrderPayment.Status.PENDING,
        amount=order.total,
        currency="EUR",
        provider="manual",
    )

    settings.CASHIER_DEVICE_TOKEN = "secret-token"
    resp = client.post(
        f"/cashier/device/payments/{payment.public_id}/cash/",
        HTTP_X_DEVICE_TOKEN="wrong-token",
    )

    assert resp.status_code == 403
    assert b"invalid device token" in resp.content


@pytest.mark.django_db
def test_device_card_confirm_requires_open_session(client, user_factory, org_factory, settings):
    user = user_factory(email="cashier@example.com")
    org = org_factory(name="Cashier Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    terminal = Terminal.objects.create(org=org, name="POS 1", code="pos-1", status=Terminal.STATUS_ACTIVE)
    product = _prepare_product(org=org)
    order = Order.objects.create(org=org, status=Order.STATUS_DRAFT)
    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("1.000"),
        unit=product.unit,
        unit_price=product.unit_price,
        tax_rate=product.tax_rate,
    )
    order.recompute_totals()
    order.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        terminal=terminal,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.PENDING,
        amount=order.total,
        currency="EUR",
        provider="manual",
    )

    settings.CASHIER_DEVICE_TOKEN = "secret-token"
    resp = client.post(
        f"/cashier/device/payments/{payment.public_id}/card/",
        HTTP_X_DEVICE_TOKEN="secret-token",
    )

    assert resp.status_code == 403
    assert b"no open session" in resp.content
