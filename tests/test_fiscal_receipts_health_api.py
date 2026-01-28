from decimal import Decimal

import pytest

from apps.orders.models import Order
from apps.payments.models import DeviceCommand, OrderPayment


@pytest.mark.django_db
def test_fiscal_receipts_health_counts_unsent(admin_client):
    client, user, org = admin_client

    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
    )

    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        status=DeviceCommand.Status.PENDING,
        idempotency_key="health:pending",
    )
    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_REFUND,
        status=DeviceCommand.Status.SENT,
        idempotency_key="health:sent",
    )
    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_STORNO,
        status=DeviceCommand.Status.FAILED,
        idempotency_key="health:failed",
    )
    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        status=DeviceCommand.Status.ACKED,
        idempotency_key="health:acked",
    )

    resp = client.get("/api/v1/health/fiscal-receipts/")
    assert resp.status_code == 200, resp.content

    data = resp.json()
    assert data["unsent_total"] == 3
    assert data["status_counts"][DeviceCommand.Status.PENDING] == 1
    assert data["status_counts"][DeviceCommand.Status.SENT] == 1
    assert data["status_counts"][DeviceCommand.Status.FAILED] == 1
