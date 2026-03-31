import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_cancel_order_locks_order_row_select_for_update(admin_client, monkeypatch):
    client, user, org = admin_client

    from apps.orders.logic.pay_order import pay_order
    from apps.orders.logic.cancel_order import cancel_order
    from apps.orders.models import Order, OrderItem
    from apps.products.models import Product, Unit, TaxRate
    from apps.inventory.services.receive_stock import receive_stock

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

    pay_order(order=order)

    called = {"value": False}
    original = Order.objects.select_for_update

    def wrapped_select_for_update(*args, **kwargs):
        called["value"] = True
        return original(*args, **kwargs)

    monkeypatch.setattr(Order.objects, "select_for_update", wrapped_select_for_update, raising=False)

    cancelled = cancel_order(order=order)

    assert cancelled.status == Order.STATUS_CANCELLED
    assert called["value"] is True