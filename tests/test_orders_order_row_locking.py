import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_pay_order_locks_order_row_select_for_update(admin_client, monkeypatch):
    """
    GIVEN:
        - Заказ draft с item

    WHEN:
        - Вызываем use-case pay_order(order=order)

    THEN:
        - Внутри транзакции должен быть row-lock на Order:
          Order.objects.select_for_update()
    """

    # ----------------------------------------
    # Arrange
    # ----------------------------------------
    client, user, org = admin_client

    from apps.orders.logic.pay_order import pay_order
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
        product_name=product.name,  # snapshot
        qty=Decimal("2.000"),
        unit=unit,
        unit_price=Decimal("3.50"),
        tax_rate=tax,
    )

    # ----------------------------------------
    # Monkeypatch: отслеживаем вызов Order.objects.select_for_update
    # ----------------------------------------
    called = {"value": False}

    original = Order.objects.select_for_update

    def wrapped_select_for_update(*args, **kwargs):
        # фиксируем факт row-lock на заказ
        called["value"] = True
        return original(*args, **kwargs)

    monkeypatch.setattr(Order.objects, "select_for_update", wrapped_select_for_update, raising=False)

    # ----------------------------------------
    # Act
    # ----------------------------------------
    paid = pay_order(order=order)

    # ----------------------------------------
    # Assert
    # ----------------------------------------
    assert paid.status == Order.STATUS_PAID
    assert called["value"] is True
