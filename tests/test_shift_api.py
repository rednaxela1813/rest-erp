from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from apps.orders.models import Order, OrderItem
from apps.payments.logic.shift import close_shift, open_shift
from apps.payments.models import OrderPayment, Terminal
from apps.products.models import Product, TaxRate, Unit

from apps.inventory.services.receive_stock import receive_stock


@pytest.mark.django_db
def test_open_close_shift_and_report(admin_client, capture_payment_api):
    client, user, org = admin_client

    terminal = Terminal.objects.create(org=org, name="Front POS", status=Terminal.STATUS_ACTIVE)

    open_resp = client.post(
        "/api/v1/shifts/open/",
        data={"terminal": str(terminal.public_id), "opening_cash": "10.00"},
        content_type="application/json",
    )
    assert open_resp.status_code == 200, open_resp.content
    shift_id = open_resp.json()["shift"]

    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    product = Product.objects.create(
        org=org,
        name="Burger",
        status=Product.STATUS_ACTIVE,
        unit=unit,
        tax_rate=tax,
        unit_price=Decimal("5.00"),
        
    )
    
    receive_stock(org=org, product=product, initial_qty=Decimal("10.000"), unit_cost=Decimal("1.00"), label_code=f"LOT-{product.name.upper()}")

    order = Order.objects.create(org=org)
    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("1.000"),
        unit=unit,
        unit_price=Decimal("5.00"),
        tax_rate=tax,
    )
    order.recompute_totals()
    order.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        terminal=terminal,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.AUTHORIZED,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
    )

    resp_pay = capture_payment_api(client, payment)
    assert resp_pay.status_code == 200, resp_pay.content

    close_resp = client.post(
        f"/api/v1/shifts/{shift_id}/close/",
        data={"closing_cash": "20.00"},
        content_type="application/json",
    )
    assert close_resp.status_code == 200, close_resp.content

    report = client.get(f"/api/v1/shifts/{shift_id}/report/")
    assert report.status_code == 200, report.content

    data = report.json()
    assert data["totals"]["payments_total"] == "5.00"
    assert data["totals"]["tax_total"] == "0.83"
    assert data["totals"]["by_tender"]["card"] == "5.00"
    assert data["totals"]["by_tax_rate"] == [{"rate": "20.00", "tax_total": "0.83"}]


@pytest.mark.django_db
def test_open_shift_is_idempotent_for_same_cashier(org_factory, user_factory):
    org = org_factory()
    cashier = user_factory(email="cashier@example.com")
    terminal = Terminal.objects.create(org=org, name="POS 1", code="pos-1", status=Terminal.STATUS_ACTIVE)

    first = open_shift(
        org=org,
        terminal=terminal,
        cashier=cashier,
        opening_cash=Decimal("10.00"),
    )
    second = open_shift(
        org=org,
        terminal=terminal,
        cashier=cashier,
        opening_cash=Decimal("99.00"),
    )

    assert first.id == second.id


@pytest.mark.django_db
def test_open_shift_rejects_other_cashier_when_terminal_already_open(org_factory, user_factory):
    org = org_factory()
    cashier_1 = user_factory(email="cashier1@example.com")
    cashier_2 = user_factory(email="cashier2@example.com")
    terminal = Terminal.objects.create(org=org, name="POS 1", code="pos-1", status=Terminal.STATUS_ACTIVE)

    open_shift(
        org=org,
        terminal=terminal,
        cashier=cashier_1,
        opening_cash=Decimal("10.00"),
    )

    with pytest.raises(ValidationError, match="Terminal already has an open shift"):
        open_shift(
            org=org,
            terminal=terminal,
            cashier=cashier_2,
            opening_cash=Decimal("5.00"),
        )


@pytest.mark.django_db
def test_close_shift_rejects_already_closed_session(org_factory, user_factory):
    from apps.payments.models import CashierSession

    org = org_factory()
    cashier = user_factory(email="cashier@example.com")
    terminal = Terminal.objects.create(org=org, name="POS 1", code="pos-1", status=Terminal.STATUS_ACTIVE)
    session = CashierSession.objects.create(
        org=org,
        terminal=terminal,
        cashier=cashier,
        cash_drawer_start=Decimal("0.00"),
        status=CashierSession.STATUS_CLOSED,
    )

    with pytest.raises(ValidationError, match="Shift is already closed"):
        close_shift(session=session, closing_cash=Decimal("1.00"))
