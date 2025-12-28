import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_cancel_order_locks_order_row_select_for_update(admin_client, monkeypatch):
    """
    GIVEN:
        - Заказ paid (т.е. уже оплачен) и его можно отменять

    WHEN:
        - Вызываем use-case cancel_order(order=order)

    THEN:
        - Внутри транзакции должен быть row-lock на Order:
          Order.objects.select_for_update()
    """

    # ----------------------------------------
    # Arrange
    # ----------------------------------------
    client, user, org = admin_client

    from apps.orders.logic.pay_order import pay_order
    from apps.orders.logic.cancel_order import cancel_order
    from apps.orders.models import Order, OrderItem
    from apps.products.models import Product, Unit, TaxRate

    order = Order.objects.create(org=org)

    product = Product.objects.create(
        org=org,
        name="Cola",
        status=Product.STATUS_ACTIVE,
        stock_qty=Decimal("10.000"),
    )
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("2.000"),
        unit=unit,
        unit_price=Decimal("3.50"),
        tax_rate=tax,
    )

    # Оплачиваем, чтобы cancel был разрешён
    pay_order(order=order)

    # ----------------------------------------
    # Monkeypatch: отслеживаем вызов Order.objects.select_for_update
    # ----------------------------------------
    called = {"value": False}

    original = Order.objects.select_for_update

    def wrapped_select_for_update(*args, **kwargs):
        called["value"] = True
        return original(*args, **kwargs)

    monkeypatch.setattr(Order.objects, "select_for_update", wrapped_select_for_update, raising=False)

    # ----------------------------------------
    # Act
    # ----------------------------------------
    cancelled = cancel_order(order=order)

    # ----------------------------------------
    # Assert
    # ----------------------------------------
    assert cancelled.status == Order.STATUS_CANCELLED
    assert called["value"] is True
