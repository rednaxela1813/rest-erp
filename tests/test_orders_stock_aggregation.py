import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_pay_order_aggregates_qty_per_product_and_fails_if_total_exceeds_stock(admin_client):
    """
    GIVEN:
        - Один заказ (draft)
        - Один продукт с ограниченным stock
        - Несколько OrderItem с ОДНИМ И ТЕМ ЖЕ Product

    WHEN:
        - Пытаемся оплатить заказ (draft -> paid)

    THEN:
        - qty по одному Product должна СУММИРОВАТЬСЯ
        - если суммарное qty > stock:
            * оплата запрещена (400)
            * статус заказа НЕ меняется
            * stock НЕ списывается

    Этот тест защищает POS-инвариант:
    ❗ нельзя проверять и списывать stock "по item'ам", только по продукту в целом
    """

    # ----------------------------------------
    # Arrange (подготовка данных)
    # ----------------------------------------
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate

    # Создаём пустой заказ в статусе draft
    order = Order.objects.create(org=org)

    # Создаём продукт с ограниченным складом
    # stock = 4
    product = Product.objects.create(
        org=org,
        name="Cola",
        status="active",
        stock_qty=Decimal("4"),
    )

    # Единица измерения и налог (валидные, из той же org)
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("0.20"))

    # ----------------------------------------
    # Act 1: добавляем первый item (qty = 2)
    # ----------------------------------------
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

    # ----------------------------------------
    # Act 2: добавляем ВТОРОЙ item
    # ТОТ ЖЕ product, qty = 3
    #
    # ВАЖНО:
    #   по отдельности (2 и 3) каждый item "влезает" в stock,
    #   но суммарно 2 + 3 = 5 > stock 4
    # ----------------------------------------
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
    # Act 3: пытаемся оплатить заказ
    # ----------------------------------------
    resp = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": "paid"},
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )

    # ----------------------------------------
    # Assert (проверяем бизнес-инварианты)
    # ----------------------------------------

    # Оплата должна быть запрещена
    assert resp.status_code == 400
    assert resp.json() == {"order": "Insufficient stock."}

    # Статус заказа НЕ должен измениться
    order.refresh_from_db()
    assert order.status == Order.STATUS_DRAFT

    # Stock продукта НЕ должен измениться
    product.refresh_from_db()
    assert product.stock_qty == Decimal("4")
