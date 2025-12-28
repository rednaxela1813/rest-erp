import pytest

pytestmark = pytest.mark.django_db


def test_cannot_set_invalid_order_status(admin_client):
    client, user, org = admin_client
    from apps.orders.models import Order

    order = Order.objects.create(org=org)

    resp = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": "not-a-real-status"},
        content_type="application/json",
    )

    assert resp.status_code == 400
    data = resp.json()
    assert "status" in data
