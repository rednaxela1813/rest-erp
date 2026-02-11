import pytest

from apps.orders.models import Order
from apps.payments.logic.device_commands import pull_device_commands
from apps.payments.models import DeviceCommand, OrderPayment


@pytest.mark.django_db
def test_pull_device_commands_filters_by_type(org_factory, payment_factory):
    org = org_factory()
    order = Order.objects.create(org=org)
    payment = payment_factory(order=order, org=org, amount="5.00")

    sale_cmd = DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        idempotency_key="sale:1",
    )
    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.PRINT_RECEIPT,
        idempotency_key="print:1",
    )

    commands = pull_device_commands(
        org=org,
        limit=10,
        command_types=[DeviceCommand.Type.FISCALIZE_SALE],
    )

    assert [cmd.id for cmd in commands] == [sale_cmd.id]
