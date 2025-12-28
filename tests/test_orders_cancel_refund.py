# tests/test_orders_cancel_refund.py
from decimal import Decimal

import pytest


@pytest.mark.django_db
def test_cancel_paid_order_restores_stock_and_sets_status_cancelled(admin_client):
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

    product = Product.objects.create(
        org=org,
        name="Cola",
        status="active",
        stock_qty=Decimal("10"),
    )
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("0.20"))

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
    assert resp.status_code == 201, resp.content

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
    assert resp.status_code == 201, resp.content

    # NEW: создаём captured payment, иначе pay запретится раньше склада
    seed_captured_payment(order)

    # pay -> stock should deduct
    resp = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": "paid"},
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp.status_code == 200, resp.content

    product.refresh_from_db()
    assert product.stock_qty == Decimal("5")  # 10 - (2+3)

    # cancel -> stock restore
    resp = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": "cancelled"},
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp.status_code == 200, resp.content

    order.refresh_from_db()
    assert order.status == Order.STATUS_CANCELLED

    product.refresh_from_db()
    assert product.stock_qty == Decimal("10")
