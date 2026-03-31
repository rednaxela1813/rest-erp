import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_order_cannot_be_paid_twice(admin_client, payment_factory, capture_payment_api, lot_factory):
    client, user, org = admin_client
    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate

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

    # first pay -> OK
    payment1 = payment_factory(order=order, org=org, amount=Decimal("7.00"))
    resp1 = capture_payment_api(client, payment1)
    assert resp1.status_code == 200

    # second pay -> must fail and NOT touch stock
    payment2 = payment_factory(order=order, org=org, amount=Decimal("7.00"))
    resp2 = capture_payment_api(client, payment2)
    assert resp2.status_code == 400
    assert resp2.json() == {"status": ["Order is already paid."]}

    order.refresh_from_db()
    assert order.status == "paid"