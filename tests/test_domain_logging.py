import time
from decimal import Decimal

import pytest

from apps.inventory.exceptions import InsufficientStock, LotNotFound
from apps.cashier import views as cashier_views
from apps.inventory.services.deduct_stock import deduct_stock
from apps.inventory.services.issue_stock import issue_by_scanned_lot
from apps.inventory.services.receive_stock import receive_stock
from apps.orders.logic.finalize_paid_order import finalize_paid_order
from apps.orders.models import Order, OrderItem
from apps.payments.logic.authorize_payment import authorize_payment
from apps.payments.logic.device_commands import ack_device_command, pull_device_commands, release_due_device_commands
from apps.payments.logic.shift import close_shift, open_shift, shift_report
from apps.payments.logic.start_payment import start_payment
from apps.payments.models import CashierSession, DeviceCommand, OrderPayment, Terminal
from apps.payments.tasks import (
    dispatch_device_commands,
    process_device_commands_mock,
    reconcile_payment_capture,
    reconcile_payment_fiscal_status_for_all_orgs,
)
from apps.products.models import Product, TaxRate, Unit
from config.orgs.models import OrganizationMember


pytestmark = pytest.mark.django_db


class StubLogger:
    def __init__(self):
        self.events = []

    def info(self, event, **kwargs):
        self.events.append(("info", event, kwargs))

    def warning(self, event, **kwargs):
        self.events.append(("warning", event, kwargs))


def _make_product(*, org, name="Cola", product_type=Product.PRODUCT_TYPE_SIMPLE) -> Product:
    unit = Unit.objects.create(org=org, name=f"{name} unit", status=Unit.STATUS_ACTIVE)
    tax_rate = TaxRate.objects.create(org=org, name=f"{name} tax", rate=Decimal("20.00"))
    return Product.objects.create(
        org=org,
        name=name,
        unit=unit,
        tax_rate=tax_rate,
        unit_price=Decimal("2.50"),
        status=Product.STATUS_ACTIVE,
        product_type=product_type,
    )


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


def test_receive_stock_logs_started_and_succeeded(org_factory, monkeypatch):
    org = org_factory()
    product = _make_product(org=org)
    stub = StubLogger()

    monkeypatch.setattr("apps.inventory.services.receive_stock.logger", stub)

    lot, movement = receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.20"),
        label_code="LOT-LOG-001",
    )

    assert stub.events[0][0] == "info"
    assert stub.events[0][1] == "stock_receive_started"
    assert stub.events[0][2]["product_name"] == product.name
    assert stub.events[1][0] == "info"
    assert stub.events[1][1] == "stock_receive_succeeded"
    assert stub.events[1][2]["movement_id"] == str(movement.id)
    assert stub.events[1][2]["label_code"] == lot.label_code


def test_deduct_stock_logs_insufficient_warning(org_factory, monkeypatch):
    org = org_factory()
    product = _make_product(org=org)
    stub = StubLogger()

    monkeypatch.setattr("apps.inventory.services.deduct_stock.logger", stub)
    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("2.000"),
        unit_cost=Decimal("1.20"),
        label_code="LOT-LOG-002",
    )

    with pytest.raises(InsufficientStock):
        deduct_stock(
            org=org,
            product=product,
            quantity=Decimal("5.000"),
            reason="order_paid",
        )

    assert stub.events[0][1] == "stock_deduct_started"
    assert stub.events[1][0] == "warning"
    assert stub.events[1][1] == "stock_deduct_insufficient"
    assert stub.events[1][2]["product_name"] == product.name


def test_issue_scanned_lot_logs_not_found_warning(org_factory, monkeypatch):
    org = org_factory()
    stub = StubLogger()

    monkeypatch.setattr("apps.inventory.services.issue_stock.logger", stub)

    with pytest.raises(LotNotFound):
        issue_by_scanned_lot(
            org=org,
            label_code="MISSING-LOT",
            quantity=Decimal("1.000"),
        )

    assert stub.events[0][1] == "stock_issue_scanned_started"
    assert stub.events[1][0] == "warning"
    assert stub.events[1][1] == "stock_issue_scanned_lot_not_found"
    assert stub.events[1][2]["label_code"] == "MISSING-LOT"


def test_finalize_paid_order_logs_started_and_succeeded(org_factory, monkeypatch):
    org = org_factory()
    product = _make_product(org=org, name="Burger")
    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.00"),
        label_code="LOT-LOG-003",
    )

    order = Order.objects.create(org=org)
    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("2.000"),
        unit=product.unit,
        unit_price=product.unit_price,
        tax_rate=product.tax_rate,
    )
    order.recompute_totals()
    order.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])

    stub = StubLogger()
    monkeypatch.setattr("apps.orders.logic.finalize_paid_order.logger", stub)

    finalize_paid_order(order=order)

    assert stub.events[0][0] == "info"
    assert stub.events[0][1] == "order_finalize_started"
    assert stub.events[0][2]["order_id"] == str(order.public_id)
    assert stub.events[-1][0] == "info"
    assert stub.events[-1][1] == "order_finalize_succeeded"
    assert stub.events[-1][2]["inventory_products_count"] == 1


def test_start_payment_logs_create_and_reuse(org_factory, monkeypatch):
    org = org_factory()
    order = Order.objects.create(org=org)
    stub = StubLogger()

    monkeypatch.setattr("apps.payments.logic.start_payment.logger", stub)

    payment = start_payment(
        order=order,
        tender=OrderPayment.Tender.CARD,
        amount=Decimal("10.00"),
        currency="EUR",
        idempotency_key="pay-log-1",
    )
    reused = start_payment(
        order=order,
        tender=OrderPayment.Tender.CARD,
        amount=Decimal("10.00"),
        currency="EUR",
        idempotency_key="pay-log-1",
    )

    assert payment.id == reused.id
    assert stub.events[0][1] == "payment_start_requested"
    assert stub.events[1][1] == "payment_start_created"
    assert stub.events[2][1] == "payment_start_requested"
    assert stub.events[3][1] == "payment_start_reused_existing"


def test_authorize_payment_logs_missing_session_warning(org_factory, monkeypatch):
    org = org_factory()
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.PENDING,
        amount=Decimal("10.00"),
        currency="EUR",
        provider="manual",
    )
    stub = StubLogger()

    monkeypatch.setattr("apps.payments.logic.authorize_payment.logger", stub)

    with pytest.raises(Exception):
        authorize_payment(payment=payment, actor=None, terminal=None, session=None)

    assert stub.events[0][1] == "payment_authorize_started"
    assert stub.events[1][0] == "warning"
    assert stub.events[1][1] == "payment_authorize_missing_open_session"


def test_device_command_logging_for_pull_ack_and_release(org_factory, monkeypatch):
    org = org_factory()
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.AUTHORIZED,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
    )
    command = DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.PAYMENT_CAPTURE,
        idempotency_key="cmd-log-1",
        status=DeviceCommand.Status.PENDING,
    )
    stub = StubLogger()

    monkeypatch.setattr("apps.payments.logic.device_commands.logger", stub)

    commands = pull_device_commands(org=org, limit=10)
    ack_device_command(command=command, status=DeviceCommand.Status.FAILED, error="timeout")
    release_due_device_commands(org=org)

    assert commands
    assert stub.events[0][1] == "device_commands_pull_started"
    assert stub.events[1][1] == "device_commands_pull_succeeded"
    assert stub.events[2][1] == "device_command_ack_started"
    assert stub.events[3][1] == "device_command_ack_succeeded"
    assert stub.events[4][1] == "device_commands_release_due_completed"


def test_shift_logging_for_open_report_close(org_factory, user_factory, monkeypatch):
    org = org_factory()
    cashier = user_factory(email="cashier-log@example.com")
    terminal = Terminal.objects.create(org=org, name="POS 1", code="pos-1", status=Terminal.STATUS_ACTIVE)
    stub = StubLogger()

    monkeypatch.setattr("apps.payments.logic.shift.logger", stub)

    session = open_shift(
        org=org,
        terminal=terminal,
        cashier=cashier,
        opening_cash=Decimal("10.00"),
    )
    report = shift_report(session=session)
    close_shift(session=session, closing_cash=Decimal("12.00"))

    assert report["payments_total"] == Decimal("0.00")
    assert stub.events[0][1] == "shift_open_started"
    assert stub.events[1][1] == "shift_open_succeeded"
    assert stub.events[2][1] == "shift_report_started"
    assert stub.events[3][1] == "shift_report_succeeded"
    assert stub.events[4][1] == "shift_close_started"
    assert stub.events[5][1] == "shift_close_succeeded"


def test_cashier_session_open_logs_invalid_selection(client, user_factory, org_factory, monkeypatch):
    user = user_factory(email="cashier-log@example.com")
    org = org_factory(name="Cashier Log Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    stub = StubLogger()

    monkeypatch.setattr("apps.cashier.views.logger", stub)

    response = client.post(
        "/cashier/session/open/",
        data={"org_id": str(org.public_id), "terminal_id": "999999", "opening_cash": "10.00"},
    )

    assert response.status_code == 200
    assert stub.events[0][1] == "cashier_session_open_requested"
    assert stub.events[1][0] == "warning"
    assert stub.events[1][1] == "cashier_session_open_invalid_selection"


def test_cashier_checkout_logs_invalid_product_config(client, user_factory, org_factory, monkeypatch):
    user = user_factory(email="cashier-checkout@example.com")
    org = org_factory(name="Cashier Checkout Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    _prepare_cashier_session(client=client, org=org, user=user)
    broken = Product.objects.create(
        org=org,
        name="Broken product",
        unit=None,
        tax_rate=None,
        unit_price=Decimal("5.00"),
    )
    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(broken.id): 1}
    session_data.save()
    stub = StubLogger()

    monkeypatch.setattr("apps.cashier.views.logger", stub)

    response = client.post("/cashier/checkout/", data={"tender": "cash"})

    assert response.status_code == 302
    assert stub.events[0][1] == "cashier_checkout_requested"
    assert stub.events[1][0] == "warning"
    assert stub.events[1][1] == "cashier_checkout_invalid_product_config"


def test_cashier_retry_fiscal_logs_started_and_succeeded(client, user_factory, org_factory, monkeypatch):
    user = user_factory(email="cashier-retry@example.com")
    org = org_factory(name="Cashier Retry Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    _prepare_cashier_session(client=client, org=org, user=user)
    product = _make_product(org=org, name="Burger")
    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.00"),
        label_code="LOT-CASHIER-LOG",
    )
    order = Order.objects.create(org=org)
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
        tender=OrderPayment.Tender.CASH,
        terminal=Terminal.objects.filter(org=org).first(),
        status=OrderPayment.Status.CAPTURED,
        amount=order.total,
        currency="EUR",
        provider="manual",
        fiscal_status=OrderPayment.FiscalStatus.FAILED,
        failure_reason="vat rejected",
    )
    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        status=DeviceCommand.Status.FAILED,
        idempotency_key="cashier:retry",
        last_error="vat rejected",
    )
    stub = StubLogger()

    monkeypatch.setattr("apps.cashier.views.logger", stub)

    response = client.post(f"/cashier/payments/{payment.public_id}/retry-fiscal/")

    assert response.status_code == 302
    assert stub.events[0][1] == "cashier_payment_retry_fiscal_started"
    assert stub.events[1][1] == "cashier_payment_retry_fiscal_succeeded"


def test_cashier_device_cash_confirm_logs_invalid_token(client, user_factory, org_factory, settings, monkeypatch):
    user = user_factory(email="cashier-device@example.com")
    org = org_factory(name="Cashier Device Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    terminal = Terminal.objects.create(org=org, name="POS 1", code="pos-1", status=Terminal.STATUS_ACTIVE)
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        terminal=terminal,
        tender=OrderPayment.Tender.CASH,
        status=OrderPayment.Status.PENDING,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
    )
    stub = StubLogger()
    settings.CASHIER_DEVICE_TOKEN = "secret-token"

    monkeypatch.setattr("apps.cashier.views.logger", stub)

    response = client.post(
        f"/cashier/device/payments/{payment.public_id}/cash/",
        data="",
        content_type="application/json",
        HTTP_X_DEVICE_TS=str(int(time.time())),
        HTTP_X_DEVICE_SIG="wrong-token",
    )

    assert response.status_code == 401
    assert stub.events[0][0] == "warning"
    assert stub.events[0][1] == "device_auth_failed"


def test_dispatch_device_commands_task_logs_started_and_succeeded(org_factory, monkeypatch):
    org = org_factory()
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.AUTHORIZED,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
    )
    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.PAYMENT_CAPTURE,
        idempotency_key="log:dispatch",
    )
    stub = StubLogger()

    monkeypatch.setattr("apps.payments.tasks.logger", stub)
    monkeypatch.setattr("apps.payments.tasks.publish_device_commands", lambda commands: len(commands))

    result = dispatch_device_commands.run(org_id=org.id, limit=10)

    assert result["published"] == 1
    assert stub.events[0][1] == "task_dispatch_device_commands_started"
    assert stub.events[-1][1] == "task_dispatch_device_commands_succeeded"


def test_process_device_commands_mock_logs_validation_failure(org_factory, settings, monkeypatch):
    settings.FISCAL_MOCK_OFFLINE = False
    org = org_factory()
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
    )
    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        payload={"order_id": str(order.public_id), "payment_id": str(payment.public_id), "amount": str(payment.amount)},
        idempotency_key="log:mock-validation",
    )
    stub = StubLogger()

    monkeypatch.setattr("apps.payments.tasks.logger", stub)

    result = process_device_commands_mock.run(org_id=org.id, limit=10)

    assert result["failed"] == 1
    assert stub.events[0][1] == "task_process_device_commands_mock_started"
    assert any(event[1] == "task_process_device_commands_mock_validation_failed" for event in stub.events)
    assert stub.events[-1][1] == "task_process_device_commands_mock_succeeded"


def test_reconcile_payment_capture_task_logs_confirmed(org_factory, monkeypatch):
    org = org_factory()
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
        capture_status=OrderPayment.CaptureStatus.PENDING,
    )
    stub = StubLogger()

    monkeypatch.setattr("apps.payments.tasks.logger", stub)

    result = reconcile_payment_capture.run(payment_id=payment.id)

    assert result["updated"] is True
    assert stub.events[0][1] == "task_reconcile_payment_capture_started"
    assert stub.events[1][1] == "task_reconcile_payment_capture_confirmed"


def test_reconcile_payment_fiscal_for_all_orgs_task_logs_started_and_succeeded(org_factory, monkeypatch):
    org = org_factory()
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
    )
    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        status=DeviceCommand.Status.SENT,
        idempotency_key="log:fiscal-all",
    )
    stub = StubLogger()

    monkeypatch.setattr("apps.payments.tasks.logger", stub)
    monkeypatch.setattr(
        "apps.payments.tasks.reconcile_payment_fiscal_status",
        lambda *, payment_id: {"updated": True},
    )

    result = reconcile_payment_fiscal_status_for_all_orgs.run(limit=10)

    assert result["processed"] == 1
    assert stub.events[0][1] == "task_reconcile_payment_fiscal_for_all_orgs_started"
    assert stub.events[-1][1] == "task_reconcile_payment_fiscal_for_all_orgs_succeeded"
