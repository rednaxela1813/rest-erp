import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_order_item_create_with_product_sets_snapshot_name(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order, OrderItem
    from apps.products.models import Unit, TaxRate, Product

    order = Order.objects.create(org=org)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    product = Product.objects.create(org=org, name="Burger Classic", status=Product.STATUS_ACTIVE)

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
    print("RESP:", resp.status_code, resp.json())

    assert resp.status_code == 201

    item = OrderItem.objects.get(order=order)
    assert item.product_id == product.id
    assert item.product_name == "Burger Classic"  # snapshot

    # rename product later
    product.name = "Burger Deluxe"
    product.save(update_fields=["name"])

    item.refresh_from_db()
    assert item.product_name == "Burger Classic"  # stays the same
