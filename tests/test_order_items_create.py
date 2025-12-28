import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_org_admin_can_add_order_item(admin_client):
    client, admin, org = admin_client

    from apps.orders.models import Order, OrderItem
    from apps.products.models import Unit, TaxRate, Product

    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)

    order = Order.objects.create(org=org)

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

    assert resp.status_code == 201, resp.content

    data = resp.json()
    assert data["product_name"] == "Burger"
    assert data["public_id"]

    assert OrderItem.objects.filter(order=order).count() == 1


def test_org_member_cannot_add_order_item(member_client):
    client, user, org = member_client

    from apps.orders.models import Order
    from apps.products.models import Unit, TaxRate, Product

    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)

    order = Order.objects.create(org=org)

    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "qty": "1",
            "unit": str(unit.public_id),
            "unit_price": "5.00",
            "tax_rate": str(tax.public_id),
        },
        content_type="application/json",
    )

    assert resp.status_code == 403
