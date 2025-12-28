import pytest

pytestmark = pytest.mark.django_db


def test_order_created_with_default_status_draft(admin_client):
    client, user, org = admin_client

    resp = client.post("/api/v1/orders/", content_type="application/json")
    assert resp.status_code == 201

    data = resp.json()
    assert data["status"] == "draft"
    

def test_cannot_add_item_to_paid_order(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Unit, TaxRate, Product
    from decimal import Decimal

    order = Order.objects.create(org=org, status=Order.STATUS_PAID)

    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

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

    assert resp.status_code == 400


def test_cannot_add_item_to_cancelled_order(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Unit, TaxRate, Product
    from decimal import Decimal

    order = Order.objects.create(org=org, status=Order.STATUS_CANCELLED)

    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

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

    assert resp.status_code == 400





