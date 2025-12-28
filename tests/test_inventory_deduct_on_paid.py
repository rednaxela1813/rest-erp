# tests/test_inventory_deduct_on_paid.py
from decimal import Decimal

import pytest


@pytest.mark.django_db
def test_paying_order_deducts_product_stock(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate
    from apps.payments.models import OrderPayment

    def seed_captured_payment(order: Order):
        """
        ВАЖНО: после добавления items totals пересчитываются на бэке.
        Поэтому refresh_from_db() -> берём актуальный order.total.
        """
        order.refresh_from_db()
        OrderPayment.objects.create(
            org=org,
            order=order,
            tender=OrderPayment.Tender.CASH,
            status=OrderPayment.Status.CAPTURED,
            amount=order.total,
            currency="EUR",
            provider="manual",
        )

    product = Product.objects.create(
        org=org,
        name="Burger",
        status=Product.STATUS_ACTIVE,
        stock_qty=Decimal("10.000"),
    )
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

    order = Order.objects.create(org=org)

    r1 = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "qty": "2",
            "unit": str(unit.public_id),
            "unit_price": "5.00",
            "tax_rate": str(tax.public_id),
        },
        content_type="application/json",
    )
    assert r1.status_code == 201, r1.content

    # NEW: без captured payment оплачивать нельзя
    seed_captured_payment(order)

    r2 = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": Order.STATUS_PAID},
        content_type="application/json",
    )
    assert r2.status_code == 200, r2.content

    product.refresh_from_db()
    assert product.stock_qty == Decimal("8.000")
