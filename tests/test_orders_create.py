import pytest

pytestmark = pytest.mark.django_db


def test_org_admin_can_create_order(admin_client):
    client, admin, org = admin_client

    resp = client.post("/api/v1/orders/", data={}, content_type="application/json")
    assert resp.status_code == 201, resp.content

    data = resp.json()
    assert "public_id" in data
    assert "id" not in data

    from apps.orders.models import Order
    assert Order.objects.filter(org=org).count() == 1


def test_org_member_cannot_create_order(member_client):
    client, user, org = member_client

    resp = client.post("/api/v1/orders/", data={}, content_type="application/json")
    assert resp.status_code == 403
