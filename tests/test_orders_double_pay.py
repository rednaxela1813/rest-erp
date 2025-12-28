import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_order_cannot_be_paid_twice(admin_client):
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

    # add 1 item to order (must be draft)
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

    # first pay -> OK
    resp1 = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": "paid"},
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp1.status_code == 200

    product.refresh_from_db()
    stock_after_first_pay = product.stock_qty
    assert stock_after_first_pay == Decimal("8")  # 10 - 2

    # second pay -> must fail and NOT touch stock
    resp2 = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": "paid"},
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp2.status_code == 400
    assert resp2.json() == {"status": ["Order is already paid."]}

    product.refresh_from_db()
    order.refresh_from_db()
    assert order.status == "paid"
    assert product.stock_qty == stock_after_first_pay
