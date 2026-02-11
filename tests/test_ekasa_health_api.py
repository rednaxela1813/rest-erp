from decimal import Decimal

import pytest

from apps.orders.models import Order
from apps.payments.models import DeviceCommand, OrderPayment


@pytest.mark.django_db
def test_ekasa_health_api_returns_queue_counts(admin_client):
    client, _user, org = admin_client
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("5.00"),
        currency="EUR",
    )

    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        status=DeviceCommand.Status.PENDING,
        idempotency_key="ekasa:1",
    )
    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        status=DeviceCommand.Status.FAILED,
        idempotency_key="ekasa:2",
    )

    resp = client.get("/api/v1/health/ekasa/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["failed_total"] == 1
    assert data["status_counts"]["pending"] == 1
    assert data["status_counts"]["failed"] == 1
