import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_order_items_list_is_scoped_to_order_and_org(member_client, org_factory):
    client, user, org_1 = member_client
    org_2 = org_factory(name="Other Org")

    from apps.orders.models import Order, OrderItem
    from apps.products.models import Unit, TaxRate

    unit = Unit.objects.create(org=org_1, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org_1, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

    order_1 = Order.objects.create(org=org_1)
    order_2 = Order.objects.create(org=org_1)
    other_org_order = Order.objects.create(org=org_2)

    i1 = OrderItem.objects.create(order=order_1, product_name="Burger", qty=Decimal("1"), unit=unit, unit_price=Decimal("5.00"), tax_rate=tax)
    OrderItem.objects.create(order=order_2, product_name="Fries", qty=Decimal("1"), unit=unit, unit_price=Decimal("2.00"), tax_rate=tax)
    OrderItem.objects.create(order=other_org_order, product_name="Other", qty=Decimal("1"), unit=unit, unit_price=Decimal("1.00"), tax_rate=tax)

    resp = client.get(f"/api/v1/orders/{order_1.public_id}/items/")
    assert resp.status_code == 200, resp.content

    data = resp.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data

    assert len(items) == 1
    assert items[0]["public_id"] == str(i1.public_id)
    assert items[0]["product_name"] == "Burger"
    assert "id" not in items[0]
