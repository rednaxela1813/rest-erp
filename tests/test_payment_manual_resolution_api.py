from decimal import Decimal

import pytest

from apps.orders.models import Order
from apps.payments.models import DeviceCommand, OrderPayment


@pytest.mark.django_db
def test_payment_status_api_returns_device_command_counts(admin_client):
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
        idempotency_key="status:pending",
    )
    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.PRINT_RECEIPT,
        status=DeviceCommand.Status.FAILED,
        idempotency_key="status:failed",
    )

    resp = client.get(f"/api/v1/payments/{payment.public_id}/status/")
    assert resp.status_code == 200, resp.content

    data = resp.json()
    assert data["payment"] == str(payment.public_id)
    assert data["device_command_counts"][DeviceCommand.Status.PENDING] == 1
    assert data["device_command_counts"][DeviceCommand.Status.FAILED] == 1


@pytest.mark.django_db
def test_manual_resolution_updates_statuses(admin_client):
    client, user, org = admin_client
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.AUTHORIZED,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
    )

    payload = {
        "capture_status": OrderPayment.CaptureStatus.CONFIRMED,
        "fiscal_status": OrderPayment.FiscalStatus.FAILED,
        "failure_reason": "manual_override",
    }
    resp = client.post(
        f"/api/v1/payments/{payment.public_id}/manual-resolution/",
        data=payload,
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content

    payment.refresh_from_db()
    assert payment.capture_status == OrderPayment.CaptureStatus.CONFIRMED
    assert payment.fiscal_status == OrderPayment.FiscalStatus.FAILED
    assert payment.failure_reason == "manual_override"


@pytest.mark.django_db
def test_manual_resolution_requires_admin(member_client):
    client, user, org = member_client
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.AUTHORIZED,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
    )

    resp = client.post(
        f"/api/v1/payments/{payment.public_id}/manual-resolution/",
        data={"capture_status": OrderPayment.CaptureStatus.TIMEOUT},
        content_type="application/json",
    )
    assert resp.status_code == 403
