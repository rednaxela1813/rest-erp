import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_pay_order_aggregates_qty_per_product_and_fails_if_total_exceeds_stock(admin_client, payment_factory, capture_payment_api, lot_factory):
    """
    GIVEN:
        - Один заказ (draft)
        - Один продукт с партией на 4 единицы
        - Два OrderItem на один и тот же продукт: qty=2 и qty=3

    WHEN:
        - Пытаемся оплатить заказ

    THEN:
        - qty суммируется: 2 + 3 = 5 > остаток 4
        - оплата запрещена (400)
        - статус заказа не меняется
        - остаток в партии не меняется
    """
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate
    from apps.inventory.models import StockLot

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Cola", status="active")
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("0.20"))
    lot_factory(org=org, product=product, qty=Decimal("4.000"))

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