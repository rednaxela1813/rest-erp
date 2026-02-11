from decimal import Decimal

import pytest

from apps.orders.models import Order, OrderItem, OrderItemAddon
from apps.payments.logic.enqueue_device_commands import enqueue_payment_commands
from apps.payments.models import DeviceCommand, OrderPayment
from apps.products.models import Product, ProductAddon, TaxRate, Unit


@pytest.mark.django_db
def test_enqueue_payment_commands_includes_items(org_factory):
    org = org_factory()
    unit = Unit.objects.create(org=org, name="pcs")
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    product = Product.objects.create(
        org=org,
        name="Burger",
        unit=unit,
        tax_rate=tax,
        unit_price=Decimal("5.00"),
    )
    addon = ProductAddon.objects.create(
        product=product,
        name="Cheese",
        price=Decimal("1.00"),
    )

    order = Order.objects.create(org=org)
    item = OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("2.000"),
        unit=unit,
        unit_price=Decimal("5.00"),
        tax_rate=tax,
    )
    OrderItemAddon.objects.create(
        order_item=item,
        addon=addon,
        name=addon.name,
        price=addon.price,
        qty=Decimal("2.000"),
    )

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.AUTHORIZED,
        amount=Decimal("12.00"),
        currency="EUR",
    )

    enqueue_payment_commands(payment=payment, include_kot=False)

    command = DeviceCommand.objects.get(
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
    )
    items = command.payload.get("items", [])
    assert len(items) == 2
    assert items[0]["name"] == "Burger"
    assert items[0]["qty"] == "2.000"
    assert items[0]["unit_price"] == "5.00"
    assert items[0]["tax_rate"] == "20.00"
    assert items[1]["name"] == "Cheese"
