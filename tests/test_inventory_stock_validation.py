import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_cannot_pay_order_if_insufficient_stock(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate

    product = Product.objects.create(
        org=org,
        name="Burger",
        status=Product.STATUS_ACTIVE,
        stock_qty=Decimal("1.000"),
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
    assert r1.status_code == 201

    r2 = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": Order.STATUS_PAID},
        content_type="application/json",
    )
    assert r2.status_code == 400

    order.refresh_from_db()
    assert order.status == Order.STATUS_DRAFT

    product.refresh_from_db()
    assert product.stock_qty == Decimal("1.000")
