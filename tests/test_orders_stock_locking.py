import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_pay_order_locks_products_rows_select_for_update(admin_client, monkeypatch):
    client, user, org = admin_client

    from apps.orders.logic.pay_order import pay_order
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

    called = {"value": False}
    original = Product.objects.select_for_update

    def wrapped_select_for_update(*args, **kwargs):
        called["value"] = True
        return original(*args, **kwargs)

    monkeypatch.setattr(Product.objects, "select_for_update", wrapped_select_for_update, raising=False)

    paid = pay_order(order=order)

    assert paid.status == Order.STATUS_PAID
    assert called["value"] is True
