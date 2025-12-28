import pytest

pytestmark = pytest.mark.django_db


def test_orders_list_is_org_scoped(member_client, org_factory):
    client, user, org_1 = member_client
    org_2 = org_factory(name="Other Org")

    # появится после создания приложения apps/orders
    from apps.orders.models import Order

    o1 = Order.objects.create(org=org_1)
    o2 = Order.objects.create(org=org_1)
    Order.objects.create(org=org_2)

    resp = client.get("/api/v1/orders/")
    assert resp.status_code == 200, resp.content

    data = resp.json()
    items = data["results"] if isinstance(data, dict) and "results" in data else data

    assert len(items) == 2

    public_ids = {i["public_id"] for i in items}
    assert str(o1.public_id) in public_ids
    assert str(o2.public_id) in public_ids

    assert "id" not in items[0]
