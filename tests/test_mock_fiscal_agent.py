from decimal import Decimal

import pytest

from apps.orders.models import Order
from apps.payments.models import DeviceCommand, FiscalReceipt, OrderPayment
from apps.payments.tasks import process_device_commands_mock


def _base_payload(*, order, payment) -> dict:
    return {
        "order_id": str(order.public_id),
        "payment_id": str(payment.public_id),
        "amount": str(payment.amount),
        "currency": payment.currency,
    }


@pytest.mark.django_db
def test_mock_agent_acks_and_creates_fiscal_receipt(org_factory, settings):
    settings.FISCAL_MOCK_OFFLINE = False
    org = org_factory(name="Org")
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("9.99"),
        currency="EUR",
        provider="manual",
    )

    command = DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        payload=_base_payload(order=order, payment=payment),
        idempotency_key="fiscalize:sale:1",
    )

    result = process_device_commands_mock.run(org_id=org.id, limit=10)

    command.refresh_from_db()
    assert result["ack"] == 1
    assert command.status == DeviceCommand.Status.ACKED
    assert FiscalReceipt.objects.filter(
        payment=payment, receipt_type=FiscalReceipt.Type.SALE
    ).exists()


@pytest.mark.django_db
def test_mock_agent_offline_fails_only_fiscalize(org_factory, settings):
    settings.FISCAL_MOCK_OFFLINE = True

    org = org_factory(name="Org")
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("12.00"),
        currency="EUR",
        provider="manual",
    )

    fiscal_cmd = DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        payload=_base_payload(order=order, payment=payment),
        idempotency_key="fiscalize:sale:offline",
    )
    print_cmd = DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.PRINT_RECEIPT,
        payload=_base_payload(order=order, payment=payment),
        idempotency_key="print:receipt:offline",
    )

    result = process_device_commands_mock.run(org_id=org.id, limit=10)

    fiscal_cmd.refresh_from_db()
    print_cmd.refresh_from_db()

    assert result["failed"] == 1
    assert result["ack"] == 1
    assert fiscal_cmd.status == DeviceCommand.Status.FAILED
    assert fiscal_cmd.last_error == "offline"
    assert fiscal_cmd.retries == 1
    assert print_cmd.status == DeviceCommand.Status.ACKED


@pytest.mark.django_db
def test_mock_agent_validation_error_hard_fails(org_factory, settings):
    settings.FISCAL_MOCK_OFFLINE = False
    org = org_factory(name="Org")
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

    bad_payload = {
        "order_id": str(order.public_id),
        "payment_id": str(payment.public_id),
        "amount": str(payment.amount),
        # missing currency
    }
    command = DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        payload=bad_payload,
        idempotency_key="fiscalize:sale:missing_currency",
    )

    process_device_commands_mock.run(org_id=org.id, limit=10)

    command.refresh_from_db()
    assert command.status == DeviceCommand.Status.FAILED
    assert command.retries == command.max_retries
    assert command.next_attempt_at is None
    assert "missing_fields=currency" in command.last_error
