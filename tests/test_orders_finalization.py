import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db

def test_cannot_set_paid_order_without_items(admin_client):
    client, user, org = admin_client
    from apps.orders.models import Order

    order = Order.objects.create(org=org)  # draft, без items

    resp = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": Order.STATUS_PAID},
        content_type="application/json",
    )

    assert resp.status_code == 400

    order.refresh_from_db()
    assert order.status == Order.STATUS_DRAFT