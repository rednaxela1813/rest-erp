import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_cannot_set_paid_order_without_items(admin_client, payment_factory, capture_payment_api):
    client, user, org = admin_client
    from apps.orders.models import Order

    order = Order.objects.create(org=org)  # draft, без items

    payment = payment_factory(order=order, org=org, amount=Decimal("5.00"))
    resp = capture_payment_api(client, payment)

    assert resp.status_code == 400

    order.refresh_from_db()
    assert order.status == Order.STATUS_DRAFT
