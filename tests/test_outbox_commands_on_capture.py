from decimal import Decimal

import pytest

from apps.orders.models import Order, OrderItem
from apps.inventory.services.receive_stock import receive_stock
from apps.payments.models import DeviceCommand
from apps.products.models import Product, TaxRate, Unit


@pytest.mark.django_db
def test_capture_payment_enqueues_device_commands_with_dedup(admin_client, payment_factory, capture_payment_api):
    client, user, org = admin_client

    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    product = Product.objects.create(
        org=org,
        name="Burger",
        status=Product.STATUS_ACTIVE,
        unit=unit,
        tax_rate=tax,
        unit_price=Decimal("5.00"),
        requires_preparation=True,
    )
    receive_stock(org=org, product=product, initial_qty=Decimal("10.000"), unit_cost=Decimal("1.00"))

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

    payment = payment_factory(order=order, org=org, amount=Decimal("5.00"))

    resp = capture_payment_api(client, payment)
    assert resp.status_code == 200, resp.content

    commands = DeviceCommand.objects.filter(payment=payment).order_by("command_type")
    assert commands.count() == 4
    assert set(commands.values_list("command_type", flat=True)) == {
        DeviceCommand.Type.PAYMENT_CAPTURE,
        DeviceCommand.Type.FISCALIZE_SALE,
        DeviceCommand.Type.PRINT_RECEIPT,
        DeviceCommand.Type.PRINT_KOT,
    }

    # Trigger a second call with the same payment (idempotency should prevent duplicates).
    payment.refresh_from_db()
    resp_2 = capture_payment_api(client, payment)
    assert resp_2.status_code == 400  # capture is not allowed twice

    commands_after = DeviceCommand.objects.filter(payment=payment)
    assert commands_after.count() == 4
