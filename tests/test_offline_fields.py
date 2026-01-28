from decimal import Decimal

import pytest

from apps.orders.models import Order
from apps.payments.models import DeviceCommand, OrderPayment


@pytest.mark.django_db
def test_order_payment_offline_status_fields_default_null(org_factory):
    org = org_factory()
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

    assert payment.capture_status is None
    assert payment.fiscal_status is None


@pytest.mark.django_db
def test_device_command_next_attempt_at_default_null(org_factory):
    org = org_factory()
    order = Order.objects.create(org=org)

    command = DeviceCommand.objects.create(
        org=org,
        order=order,
        command_type=DeviceCommand.Type.PAYMENT_CAPTURE,
        idempotency_key="retry:1",
    )

    assert command.next_attempt_at is None
