import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_cancel_order_is_idempotent_and_does_not_touch_stock_when_already_cancelled(admin_client):
    """
    GIVEN:
        - Заказ draft с item
        - Мы оплачиваем заказ (stock списывается)
        - Потом отменяем (stock возвращается)

    WHEN:
        - Пытаемся отменить второй раз

    THEN:
        - Должна быть ошибка (ValidationError)
        - Stock не должен "возвращаться" повторно (не должен стать больше исходного)
        - Статус остаётся cancelled
    """

    # ----------------------------------------
    # Arrange
    # ----------------------------------------
    client, user, org = admin_client

    from rest_framework.exceptions import ValidationError
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
    # Arrange: pay -> stock списан
    # ----------------------------------------
    pay_order(order=order)
    product.refresh_from_db()
    assert product.stock_qty == Decimal("8.000")

    # ----------------------------------------
    # Act 1: cancel -> stock возвращён
    # ----------------------------------------
    cancel_order(order=order)
    product.refresh_from_db()
    assert product.stock_qty == Decimal("10.000")

    # ----------------------------------------
    # Act 2: второй cancel (должен упасть)
    # ----------------------------------------
    with pytest.raises(ValidationError):
        cancel_order(order=order)

    # ----------------------------------------
    # Assert: stock не изменился
    # ----------------------------------------
    product.refresh_from_db()
    assert product.stock_qty == Decimal("10.000")

    order.refresh_from_db()
    assert order.status == Order.STATUS_CANCELLED
