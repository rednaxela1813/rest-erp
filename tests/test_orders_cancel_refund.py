import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_cancel_paid_order_restores_stock_and_sets_status_cancelled(admin_client):
    """
    GIVEN:
        - Заказ оплачен (paid)
        - При оплате stock был списан (это уже покрыто тестами pay_order)

    WHEN:
        - Мы меняем статус заказа на cancelled

    THEN:
        - Stock возвращается обратно (refund inventory)
        - Статус заказа становится cancelled
        - Всё происходит атомарно (в следующих тестах усилим rollback/lock)
    """

    # ----------------------------------------
    # Arrange: создаём заказ и товары
    # ----------------------------------------
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate

    order = Order.objects.create(org=org)

    product = Product.objects.create(
        org=org,
        name="Cola",
        status="active",
        stock_qty=Decimal("10"),
    )
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("0.20"))

    # Добавляем 2 позиции одного и того же продукта (проверим, что возврат суммируется)
    # item1 qty=2
    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "unit": str(unit.public_id),
            "tax_rate": str(tax_rate.public_id),
            "qty": "2",
            "unit_price": "3.50",
        },
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp.status_code == 201

    # item2 qty=3
    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "unit": str(unit.public_id),
            "tax_rate": str(tax_rate.public_id),
            "qty": "3",
            "unit_price": "3.50",
        },
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp.status_code == 201

    # ----------------------------------------
    # Arrange: оплачиваем заказ (stock должен списаться)
    # ----------------------------------------
    resp = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": "paid"},
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp.status_code == 200

    product.refresh_from_db()
    # 10 - (2 + 3) = 5
    assert product.stock_qty == Decimal("5")

    # ----------------------------------------
    # Act: отменяем (cancelled) и ожидаем возврат stock
    # ----------------------------------------
    resp = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": "cancelled"},
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )

    # ----------------------------------------
    # Assert: статус и склад
    # ----------------------------------------
    assert resp.status_code == 200

    order.refresh_from_db()
    assert order.status == "cancelled"

    product.refresh_from_db()
    # Должны вернуть обратно (2 + 3) => обратно к 10
    assert product.stock_qty == Decimal("10")
