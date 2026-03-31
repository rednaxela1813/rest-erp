import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_pay_order_is_idempotent_and_does_not_touch_stock_when_already_paid(admin_client):
    client, user, org = admin_client

    from rest_framework.exceptions import ValidationError
    from apps.orders.logic.pay_order import pay_order
    from apps.orders.models import Order, OrderItem
    from apps.products.models import Product, Unit, TaxRate
    from apps.inventory.services.receive_stock import receive_stock
    from apps.inventory.models import StockLot

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Cola", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.00"),
        label_code="LOT-COLA",
    )

    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("2.000"),
        unit=unit,
        unit_price=Decimal("3.50"),
        tax_rate=tax,
    )

    # первый pay
    pay_order(order=order)

    lot = StockLot.objects.get(org=org, label_code="LOT-COLA")
    assert lot.remaining_qty == Decimal("8.000")

    # второй pay должен упасть
    with pytest.raises(ValidationError):
        pay_order(order=order)

    # остаток в партии не изменился
    lot.refresh_from_db()
    assert lot.remaining_qty == Decimal("8.000")

    order.refresh_from_db()
    assert order.status == Order.STATUS_PAID