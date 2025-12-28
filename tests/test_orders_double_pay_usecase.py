import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_pay_order_is_idempotent_and_does_not_touch_stock_when_already_paid(admin_client):
    """
    GIVEN:
        - Заказ draft с item (stock достаточный)

    WHEN:
        - Оплачиваем заказ первый раз -> OK
        - Пытаемся оплатить второй раз -> ошибка (ValidationError)

    THEN:
        - Stock списывается ровно один раз
        - Статус остаётся paid
    """

    # ----------------------------------------
    # Arrange
    # ----------------------------------------
    client, user, org = admin_client

    from rest_framework.exceptions import ValidationError
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
    tax = TaxRate.objects.create(
        org=org,
        name="VAT 20",
        rate=Decimal("20.00"),
        status=TaxRate.STATUS_ACTIVE,
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

    # ----------------------------------------
    # Act 1: первый pay
    # ----------------------------------------
    pay_order(order=order)

    product.refresh_from_db()
    assert product.stock_qty == Decimal("8.000")  # 10 - 2

    # ----------------------------------------
    # Act 2: второй pay (должен упасть)
    # ----------------------------------------
    with pytest.raises(ValidationError):
        pay_order(order=order)

    # ----------------------------------------
    # Assert: stock не изменился
    # ----------------------------------------
    product.refresh_from_db()
    assert product.stock_qty == Decimal("8.000")

    order.refresh_from_db()
    assert order.status == Order.STATUS_PAID
