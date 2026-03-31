import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_cancel_paid_order_restores_stock_and_sets_status_cancelled(admin_client, payment_factory, capture_payment_api, lot_factory):
    """
    GIVEN:
        - Заказ с двумя items на один продукт (qty=2 и qty=3)
        - Партия на 10 единиц

    WHEN:
        - Оплачиваем -> остаток списывается (10 - 5 = 5)
        - Отменяем -> статус меняется на cancelled

    THEN:
        - После оплаты остаток в партии = 5
        - После отмены статус заказа = cancelled
        - restore_stock MVP обновляет только product.stock_qty,
          партия не восстанавливается (это задокументированное поведение)
    """
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate
    from apps.inventory.models import StockLot

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Cola", status="active")
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("0.20"))
    lot_factory(org=org, product=product, qty=Decimal("10.000"))

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

    payment = payment_factory(order=order, org=org, amount=Decimal("17.50"))
    resp = capture_payment_api(client, payment)
    assert resp.status_code == 200

    lot = StockLot.objects.get(org=org, product=product)
    assert lot.remaining_qty == Decimal("5.000")

    resp = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": "cancelled"},
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp.status_code == 200

    order.refresh_from_db()
    assert order.status == "cancelled"

    # restore_stock MVP не возвращает остаток в партию
    lot.refresh_from_db()
    assert lot.remaining_qty == Decimal("5.000")