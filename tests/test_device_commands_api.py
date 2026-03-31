from decimal import Decimal

import pytest

from apps.orders.models import Order, OrderItem
from apps.payments.models import DeviceCommand
from apps.products.models import Product, TaxRate, Unit

from apps.inventory.services.receive_stock import receive_stock


@pytest.mark.django_db
def test_device_commands_pull_and_ack(admin_client, payment_factory, capture_payment_api):
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

    payment = payment_factory(order=order, org=org, amount=Decimal("5.00"))
    resp = capture_payment_api(client, payment)
    assert resp.status_code == 200, resp.content

    pull = client.get("/api/v1/device/commands/pull/?limit=10")
    assert pull.status_code == 200, pull.content

    payload = pull.json()
    assert len(payload) == 4

    # ACK one command and ensure status update is persisted.
    command_id = payload[0]["public_id"]
    ack = client.post(
        f"/api/v1/device/commands/{command_id}/ack/",
        data={"status": "acked"},
        content_type="application/json",
    )
    assert ack.status_code == 204

    cmd = DeviceCommand.objects.get(public_id=command_id)
    assert cmd.status == DeviceCommand.Status.ACKED


@pytest.mark.django_db
def test_device_command_ack_failed_increments_retries(admin_client, payment_factory, capture_payment_api):
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

    payment = payment_factory(order=order, org=org, amount=Decimal("5.00"))
    resp = capture_payment_api(client, payment)
    assert resp.status_code == 200, resp.content

    command = DeviceCommand.objects.filter(payment=payment).first()
    assert command is not None

    ack = client.post(
        f"/api/v1/device/commands/{command.public_id}/ack/",
        data={"status": "failed", "error": "printer offline"},
        content_type="application/json",
    )
    assert ack.status_code == 204

    command.refresh_from_db()
    assert command.status == DeviceCommand.Status.FAILED
    assert command.retries == 1
    assert command.last_error == "printer offline"
