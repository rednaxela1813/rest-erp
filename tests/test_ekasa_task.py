from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.orders.models import Order, OrderItem
from apps.accounting.models import AccountingEntry
from apps.inventory.models import StockLot
from apps.inventory.services.receive_stock import receive_stock
from apps.payments.models import DeviceCommand, FiscalReceipt, OrderPayment
from apps.payments.tasks import process_device_commands_ekasa
from apps.products.models import Product, TaxRate, Unit


@pytest.mark.django_db
def test_process_device_commands_ekasa_acks_and_creates_receipt(monkeypatch, settings, org_factory):
    settings.EKASA_BASE_URL = "http://localhost:3010"
    settings.EKASA_CASH_REGISTER_CODE = "KASA-1"
    settings.EKASA_ENABLED = True

    org = org_factory()
    unit = Unit.objects.create(org=org, name="pcs")
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    product = Product.objects.create(org=org, name="Burger", unit=unit, tax_rate=tax, unit_price=Decimal("5.00"))
    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.00"),
        label_code="LOT-BURGER-EKASA",
    )

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

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("5.00"),
        currency="EUR",
    )

    command = DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        payload={
            "order_id": str(order.public_id),
            "payment_id": str(payment.public_id),
            "amount": str(payment.amount),
            "currency": payment.currency,
            "items": [
                {
                    "name": "Burger",
                    "qty": "1.000",
                    "unit_price": "5.00",
                    "tax_rate": "20.00",
                    "unit": "pcs",
                }
            ],
        },
    )

    class DummyClient:
        def register_cash_register(self, *, payload):
            return {"data": {"id": "ekasa-1"}}

    monkeypatch.setattr("apps.payments.tasks.EkasaClient", lambda: DummyClient())

    result = process_device_commands_ekasa.run(org_id=org.id, limit=10)

    command.refresh_from_db()
    payment.refresh_from_db()
    order.refresh_from_db()
    assert result["ack"] == 1
    assert command.status == DeviceCommand.Status.ACKED
    assert payment.fiscal_status == OrderPayment.FiscalStatus.CONFIRMED
    assert order.status == Order.STATUS_PAID
    assert FiscalReceipt.objects.filter(payment=payment, receipt_type=FiscalReceipt.Type.SALE).exists()
    assert AccountingEntry.objects.filter(
        org=org,
        entry_type=AccountingEntry.EntryType.SALE_CARD,
    ).exists()
    lot = StockLot.objects.get(org=org, label_code="LOT-BURGER-EKASA")
    assert lot.remaining_qty == Decimal("9.000")


@pytest.mark.django_db
def test_process_device_commands_ekasa_does_not_auto_retry_stale_sent_fiscal_commands(
    monkeypatch,
    settings,
    org_factory,
):
    settings.EKASA_BASE_URL = "http://localhost:3010"
    settings.EKASA_CASH_REGISTER_CODE = "KASA-1"
    settings.EKASA_ENABLED = True
    settings.DEVICE_COMMANDS_RETRY_BASE_SECONDS = 10

    org = org_factory()
    unit = Unit.objects.create(org=org, name="pcs")
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    product = Product.objects.create(org=org, name="Burger", unit=unit, tax_rate=tax, unit_price=Decimal("5.00"))
    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.00"),
        label_code="LOT-BURGER-EKASA-STALE",
    )

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

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("5.00"),
        currency="EUR",
        fiscal_status=OrderPayment.FiscalStatus.PENDING,
    )

    command = DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        status=DeviceCommand.Status.SENT,
        payload={
            "order_id": str(order.public_id),
            "payment_id": str(payment.public_id),
            "amount": str(payment.amount),
            "currency": payment.currency,
            "items": [
                {
                    "name": "Burger",
                    "qty": "1.000",
                    "unit_price": "5.00",
                    "tax_rate": "20.00",
                    "unit": "pcs",
                }
            ],
        },
        idempotency_key="ekasa:stale-sent",
    )
    DeviceCommand.objects.filter(id=command.id).update(updated_at=timezone.now() - timedelta(seconds=30))

    class DummyClient:
        def register_cash_register(self, *, payload):
            raise AssertionError("stale fiscal command must not be retried automatically")

    monkeypatch.setattr("apps.payments.tasks.EkasaClient", lambda: DummyClient())

    result = process_device_commands_ekasa.run(org_id=org.id, limit=10)

    command.refresh_from_db()
    payment.refresh_from_db()
    order.refresh_from_db()
    assert result["released"] == 0
    assert result["processed"] == 0
    assert result["ack"] == 0
    assert result["failed"] == 0
    assert command.status == DeviceCommand.Status.SENT
    assert payment.fiscal_status == OrderPayment.FiscalStatus.PENDING
    assert order.status == Order.STATUS_DRAFT


@pytest.mark.django_db
def test_process_device_commands_ekasa_does_not_auto_retry_failed_fiscal_commands(
    monkeypatch,
    settings,
    org_factory,
):
    settings.EKASA_BASE_URL = "http://localhost:3010"
    settings.EKASA_CASH_REGISTER_CODE = "KASA-1"
    settings.EKASA_ENABLED = True
    settings.DEVICE_COMMANDS_RETRY_BASE_SECONDS = 10

    org = org_factory()
    unit = Unit.objects.create(org=org, name="pcs")
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    product = Product.objects.create(org=org, name="Burger", unit=unit, tax_rate=tax, unit_price=Decimal("5.00"))
    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.00"),
        label_code="LOT-BURGER-EKASA-FAILED",
    )

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

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("5.00"),
        currency="EUR",
        fiscal_status=OrderPayment.FiscalStatus.FAILED,
        failure_reason="ekasa offline",
    )

    command = DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        status=DeviceCommand.Status.FAILED,
        retries=1,
        max_retries=5,
        next_attempt_at=timezone.now() - timedelta(seconds=30),
        payload={
            "order_id": str(order.public_id),
            "payment_id": str(payment.public_id),
            "amount": str(payment.amount),
            "currency": payment.currency,
            "items": [
                {
                    "name": "Burger",
                    "qty": "1.000",
                    "unit_price": "5.00",
                    "tax_rate": "20.00",
                    "unit": "pcs",
                }
            ],
        },
        idempotency_key="ekasa:failed-no-auto-retry",
    )

    class DummyClient:
        def register_cash_register(self, *, payload):
            raise AssertionError("failed fiscal command must not be retried automatically")

    monkeypatch.setattr("apps.payments.tasks.EkasaClient", lambda: DummyClient())

    result = process_device_commands_ekasa.run(org_id=org.id, limit=10)

    command.refresh_from_db()
    payment.refresh_from_db()
    order.refresh_from_db()

    assert result["released"] == 0
    assert result["processed"] == 0
    assert result["ack"] == 0
    assert result["failed"] == 0
    assert command.status == DeviceCommand.Status.FAILED
    assert payment.fiscal_status == OrderPayment.FiscalStatus.FAILED
    assert order.status == Order.STATUS_DRAFT
