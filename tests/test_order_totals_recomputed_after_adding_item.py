import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_order_totals_recomputed_after_adding_item(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

    resp = client.post(
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
    assert resp.status_code == 201

    order.refresh_from_db()
    assert order.subtotal == Decimal("10.00")
    assert order.tax_total == Decimal("2.00")
    assert order.total == Decimal("12.00")


def test_cannot_patch_order_totals(admin_client):
    client, user, org = admin_client
    from apps.orders.models import Order

    order = Order.objects.create(org=org)

    resp = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={
            "subtotal": "999.99",
            "tax_total": "999.99",
            "total": "1999.98",
        },
        content_type="application/json",
    )

    assert resp.status_code == 200

    order.refresh_from_db()
    assert order.subtotal == 0
    assert order.tax_total == 0
    assert order.total == 0
    
    


