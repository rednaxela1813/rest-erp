# tests/test_orders_stock_locking.py

import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_pay_order_locks_products_rows_select_for_update(admin_client, monkeypatch):
    """
    GIVEN:
        - Заказ draft
        - В заказе есть позиции
        - Stock у продуктов достаточный

    WHEN:
        - Вызываем use-case pay_order(order=order)

    THEN:
        - Во время оплаты должен использоваться row-level lock:
          Product.objects.select_for_update()
    """

    # ----------------------------------------
    # Arrange
    # ----------------------------------------
    client, user, org = admin_client

    from apps.orders.logic.pay_order import pay_order
    from apps.orders.models import Order, OrderItem
    from apps.products.models import Product, Unit, TaxRate

    # Создаём заказ
    order = Order.objects.create(org=org)

    # Создаём продукт и справочники
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

    # Создаём OrderItem напрямую (без API),
    # чтобы тест проверял именно use-case, а не слой представлений.
    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,     # snapshot
        qty=Decimal("2.000"),
        unit=unit,
        unit_price=Decimal("3.50"),
        tax_rate=tax,
    )

    # ----------------------------------------
    # Monkeypatch: отслеживаем вызов select_for_update
    # ----------------------------------------
    called = {"value": False}

    original = Product.objects.select_for_update

    def wrapped_select_for_update(*args, **kwargs):
        # Фиксируем факт row-lock
        called["value"] = True
        return original(*args, **kwargs)

    monkeypatch.setattr(Product.objects, "select_for_update", wrapped_select_for_update, raising=False)

    # ----------------------------------------
    # Act
    # ----------------------------------------
    paid = pay_order(order=order)

    # ----------------------------------------
    # Assert
    # ----------------------------------------
    assert paid.status == Order.STATUS_PAID
    assert called["value"] is True
