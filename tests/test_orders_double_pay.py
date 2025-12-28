# tests/test_orders_double_pay.py
from decimal import Decimal

import pytest


@pytest.mark.django_db
def test_order_cannot_be_paid_twice(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate
    from apps.payments.models import OrderPayment

    def seed_captured_payment(order: Order):
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

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Cola", status="active", stock_qty=Decimal("10"))
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("0.20"))

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
    assert resp.status_code == 201, resp.content

    seed_captured_payment(order)

    resp1 = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": "paid"},
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp1.status_code == 200, resp1.content

    # второй pay -> должен быть 400
    resp2 = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": "paid"},
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp2.status_code == 400
