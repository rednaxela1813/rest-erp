from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.orders.models import Order
from apps.payments.logic.device_commands import (
    ack_device_command,
    pull_device_commands,
    release_due_device_commands,
)
from apps.payments.models import DeviceCommand, OrderPayment


@pytest.mark.django_db
def test_ack_failed_sets_next_attempt_at_and_increments_retries(org_factory, settings):
    settings.DEVICE_COMMANDS_RETRY_BASE_SECONDS = 1
    settings.DEVICE_COMMANDS_RETRY_MAX_SECONDS = 10

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
    command = DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.PAYMENT_CAPTURE,
        idempotency_key="retry:ack",
    )

    now = timezone.now()
    ack_device_command(command=command, status=DeviceCommand.Status.FAILED, error="timeout")

    command.refresh_from_db()
    assert command.status == DeviceCommand.Status.FAILED
    assert command.retries == 1
    assert command.next_attempt_at is not None
    assert command.next_attempt_at > now


@pytest.mark.django_db
def test_release_due_device_commands_moves_failed_to_pending(org_factory):
    org = org_factory()
    order = Order.objects.create(org=org)

    due_command = DeviceCommand.objects.create(
        org=org,
        order=order,
        command_type=DeviceCommand.Type.PRINT_RECEIPT,
        idempotency_key="retry:due",
        status=DeviceCommand.Status.FAILED,
        retries=1,
        max_retries=5,
        next_attempt_at=timezone.now() - timedelta(seconds=5),
    )
    future_command = DeviceCommand.objects.create(
        org=org,
        order=order,
        command_type=DeviceCommand.Type.PRINT_KOT,
        idempotency_key="retry:future",
        status=DeviceCommand.Status.FAILED,
        retries=1,
        max_retries=5,
        next_attempt_at=timezone.now() + timedelta(seconds=60),
    )
    exhausted_command = DeviceCommand.objects.create(
        org=org,
        order=order,
        command_type=DeviceCommand.Type.PAYMENT_CAPTURE,
        idempotency_key="retry:exhausted",
        status=DeviceCommand.Status.FAILED,
        retries=5,
        max_retries=5,
        next_attempt_at=timezone.now() - timedelta(seconds=5),
    )

    released = release_due_device_commands(org=org)

    due_command.refresh_from_db()
    future_command.refresh_from_db()
    exhausted_command.refresh_from_db()

    assert released == 1
    assert due_command.status == DeviceCommand.Status.PENDING
    assert future_command.status == DeviceCommand.Status.FAILED
    assert exhausted_command.status == DeviceCommand.Status.FAILED


@pytest.mark.django_db
def test_pull_device_commands_skips_future_next_attempt(org_factory):
    org = org_factory()
    order = Order.objects.create(org=org)

    future_command = DeviceCommand.objects.create(
        org=org,
        order=order,
        command_type=DeviceCommand.Type.PAYMENT_CAPTURE,
        idempotency_key="retry:skip",
        next_attempt_at=timezone.now() + timedelta(seconds=60),
    )
    ready_command = DeviceCommand.objects.create(
        org=org,
        order=order,
        command_type=DeviceCommand.Type.PRINT_RECEIPT,
        idempotency_key="retry:ready",
    )

    commands = pull_device_commands(org=org, limit=10)
    assert [cmd.id for cmd in commands] == [ready_command.id]

    future_command.refresh_from_db()
    ready_command.refresh_from_db()
    assert future_command.status == DeviceCommand.Status.PENDING
    assert ready_command.status == DeviceCommand.Status.SENT
