import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_cancel_order_rolls_back_stock_if_error_occurs_midway(admin_client, monkeypatch):
    """
    GIVEN:
        - Заказ оплачен (paid)
        - В заказе два разных продукта
        - При оплате stock уже был списан

    WHEN:
        - Во время cancel_order происходит ошибка после первого возврата stock (искусственно)

    THEN:
        - Всё откатывается:
            * заказ остаётся paid (не cancelled)
            * stock НЕ меняется ни у одного продукта (т.е. "половинчатого возврата" нет)
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

    product_a = Product.objects.create(
        org=org,
        name="A",
        status=Product.STATUS_ACTIVE,
        stock_qty=Decimal("10.000"),
    )
    product_b = Product.objects.create(
        org=org,
        name="B",
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

    # Два item на разные продукты
    OrderItem.objects.create(
        order=order,
        product=product_a,
        product_name=product_a.name,
        qty=Decimal("2.000"),
        unit=unit,
        unit_price=Decimal("1.00"),
        tax_rate=tax,
    )
    OrderItem.objects.create(
        order=order,
        product=product_b,
        product_name=product_b.name,
        qty=Decimal("3.000"),
        unit=unit,
        unit_price=Decimal("1.00"),
        tax_rate=tax,
    )

    # Оплачиваем (stock должен списаться)
    pay_order(order=order)

    product_a.refresh_from_db()
    product_b.refresh_from_db()

    # 10 - 2 = 8, 10 - 3 = 7
    assert product_a.stock_qty == Decimal("8.000")
    assert product_b.stock_qty == Decimal("7.000")

    # ----------------------------------------
    # Monkeypatch: ломаем сохранение второго продукта
    # ----------------------------------------
    original_save = Product.save
    calls = {"count": 0}

    def exploding_save(self, *args, **kwargs):
        """
        Первый save проходит (вернём stock product_a).
        Второй save падает исключением (на product_b).
        """
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("DB write failed")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(Product, "save", exploding_save)

    # ----------------------------------------
    # Act: пытаемся отменить (ожидаем исключение)
    # ----------------------------------------
    with pytest.raises(RuntimeError):
        cancel_order(order=order)

    # ----------------------------------------
    # Assert: всё должно быть откатано
    # ----------------------------------------
    order.refresh_from_db()
    assert order.status == Order.STATUS_PAID

    product_a.refresh_from_db()
    product_b.refresh_from_db()

    # Никаких "половинчатых" возвратов: остаётся как после оплаты
    assert product_a.stock_qty == Decimal("8.000")
    assert product_b.stock_qty == Decimal("7.000")
