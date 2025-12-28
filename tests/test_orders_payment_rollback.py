import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_pay_order_rolls_back_stock_if_error_occurs_midway(admin_client, monkeypatch):
    """
    GIVEN:
        - Заказ draft с двумя разными продуктами
        - Stock у обоих достаточный

    WHEN:
        - Во время оплаты происходит ошибка после первого списания (искусственно)

    THEN:
        - transaction.atomic() откатывает всё:
            * заказ остаётся draft
            * stock НЕ меняется ни у одного продукта

    ВАЖНО:
        Django test client по умолчанию "пробрасывает" необработанные исключения наружу,
        поэтому мы ожидаем RuntimeError через pytest.raises(),
        а затем проверяем состояние БД.
    """

    # ----------------------------------------
    # Arrange
    # ----------------------------------------
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate

    order = Order.objects.create(org=org)

    # Два разных продукта, stock достаточен для обоих
    product_a = Product.objects.create(
        org=org, name="A", status="active", stock_qty=Decimal("10")
    )
    product_b = Product.objects.create(
        org=org, name="B", status="active", stock_qty=Decimal("10")
    )

    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("0.20"))

    # Добавляем item на продукт A (qty=2)
    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product_a.public_id),
            "unit": str(unit.public_id),
            "tax_rate": str(tax_rate.public_id),
            "qty": "2",
            "unit_price": "1.00",
        },
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp.status_code == 201

    # Добавляем item на продукт B (qty=3)
    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product_b.public_id),
            "unit": str(unit.public_id),
            "tax_rate": str(tax_rate.public_id),
            "qty": "3",
            "unit_price": "1.00",
        },
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp.status_code == 201

    # ----------------------------------------
    # Monkeypatch: ломаем сохранение второго продукта
    # ----------------------------------------
    original_save = Product.save
    calls = {"count": 0}

    def exploding_save(self, *args, **kwargs):
        """
        Первый save проходит (спишем product_a).
        Второй save падает исключением (на product_b).
        """
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("DB write failed")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(Product, "save", exploding_save)

    # ----------------------------------------
    # Act: пытаемся оплатить
    # ----------------------------------------
    # Django test client пробрасывает необработанные исключения наружу,
    # поэтому ожидаем RuntimeError вместо проверки HTTP-кода.
    with pytest.raises(RuntimeError, match="DB write failed"):
        client.patch(
            f"/api/v1/orders/{order.public_id}/",
            data={"status": "paid"},
            content_type="application/json",
            HTTP_X_ORG_ID=str(org.public_id),
        )

    # ----------------------------------------
    # Assert: откат (rollback)
    # ----------------------------------------
    order.refresh_from_db()
    assert order.status == Order.STATUS_DRAFT

    product_a.refresh_from_db()
    product_b.refresh_from_db()
    assert product_a.stock_qty == Decimal("10")
    assert product_b.stock_qty == Decimal("10")
