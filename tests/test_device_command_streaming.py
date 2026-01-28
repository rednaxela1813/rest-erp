from decimal import Decimal

import pytest

from apps.orders.models import Order
from apps.payments.models import DeviceCommand
from apps.payments.tasks import dispatch_device_commands


class DummyRedis:
    def __init__(self):
        self.calls = []

    def xadd(self, stream, payload, maxlen=None, approximate=False):
        self.calls.append((stream, payload, maxlen, approximate))
        return "1-0"


@pytest.mark.django_db
def test_dispatch_device_commands_publishes_to_stream_and_marks_sent(
    org_factory,
    payment_factory,
    monkeypatch,
):
    org = org_factory()
    order = Order.objects.create(org=org)
    payment = payment_factory(order=order, org=org, amount=Decimal("5.00"))

    command = DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.PAYMENT_CAPTURE,
        idempotency_key="cmd:1",
    )

    dummy_redis = DummyRedis()
    monkeypatch.setattr("apps.payments.streaming.get_redis_client", lambda: dummy_redis)

    result = dispatch_device_commands.run(org_id=org.id, limit=10)

    command.refresh_from_db()
    assert command.status == DeviceCommand.Status.SENT
    assert result["published"] == 1
    assert result["command_ids"] == [str(command.public_id)]

    assert dummy_redis.calls, "Expected Redis stream publish to be called."
    stream, payload, maxlen, approximate = dummy_redis.calls[0]
    assert payload["public_id"] == str(command.public_id)
    assert payload["command_type"] == DeviceCommand.Type.PAYMENT_CAPTURE
    assert payload["payload"] == "{}"
    assert payload["order"] == str(order.public_id)
    assert payload["payment"] == str(payment.public_id)
