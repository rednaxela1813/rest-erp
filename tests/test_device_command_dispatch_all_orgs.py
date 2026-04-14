from decimal import Decimal

import pytest
from django.test import override_settings

from apps.orders.models import Order
from apps.payments.models import DeviceCommand, OrderPayment
from apps.payments.tasks import dispatch_device_commands_for_all_orgs


@pytest.mark.django_db
@override_settings(EKASA_ENABLED=False)
def test_dispatch_device_commands_for_all_orgs_processes_each_org(
    org_factory,
    monkeypatch,
):
    org_one = org_factory(name="Org One")
    org_two = org_factory(name="Org Two")

    # Создаём данные для двух организаций
    order_one = Order.objects.create(org=org_one)
    payment_one = OrderPayment.objects.create(
        org=org_one,
        order=order_one,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.AUTHORIZED,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
    )
    DeviceCommand.objects.create(
        org=org_one,
        order=order_one,
        payment=payment_one,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        idempotency_key="org1:fiscal",
    )

    order_two = Order.objects.create(org=org_two)
    payment_two = OrderPayment.objects.create(
        org=org_two,
        order=order_two,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.AUTHORIZED,
        amount=Decimal("7.00"),
        currency="EUR",
        provider="manual",
    )
    DeviceCommand.objects.create(
        org=org_two,
        order=order_two,
        payment=payment_two,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        idempotency_key="org2:fiscal",
    )

    # Теперь проверяем не выполнение, а постановку в очередь
    dispatched_org_ids = []

    def fake_delay(*, org_id, limit):
        dispatched_org_ids.append(org_id)

    monkeypatch.setattr(
        "apps.payments.tasks.dispatch_device_commands.delay",
        fake_delay,
    )

    result = dispatch_device_commands_for_all_orgs.run(limit=10)

    assert result["orgs_processed"] == 2
    assert org_one.id in dispatched_org_ids
    assert org_two.id in dispatched_org_ids