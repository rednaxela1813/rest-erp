from decimal import Decimal

import pytest

from apps.orders.models import Order, OrderItem
from apps.payments.models import DeviceCommand, FiscalReceipt, OrderPayment
from apps.payments.tasks import process_device_commands_ekasa
from apps.products.models import Product, TaxRate, Unit


@pytest.mark.django_db
def test_process_device_commands_ekasa_acks_and_creates_receipt(monkeypatch, settings, org_factory):
    settings.EKASA_BASE_URL = "http://localhost:3010"
    settings.EKASA_CASH_REGISTER_CODE = "KASA-1"

    org = org_factory()
    unit = Unit.objects.create(org=org, name="pcs")
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    product = Product.objects.create(org=org, name="Burger", unit=unit, tax_rate=tax, unit_price=Decimal("5.00"))

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
    assert result["ack"] == 1
    assert command.status == DeviceCommand.Status.ACKED
    assert payment.fiscal_status == OrderPayment.FiscalStatus.CONFIRMED
    assert FiscalReceipt.objects.filter(payment=payment, receipt_type=FiscalReceipt.Type.SALE).exists()
