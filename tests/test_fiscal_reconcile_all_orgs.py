from decimal import Decimal

import pytest

from apps.orders.models import Order
from apps.payments.models import DeviceCommand, OrderPayment
from apps.payments.tasks import reconcile_payment_fiscal_status_for_all_orgs


@pytest.mark.django_db
def test_reconcile_payment_fiscal_status_for_all_orgs_targets_only_stuck_payments(monkeypatch, org_factory):
    org = org_factory()
    order = Order.objects.create(org=org)

    # Payment with a SENT fiscal command should be reconciled.
    payment_stuck = OrderPayment.objects.create(
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
        payment=payment_stuck,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        status=DeviceCommand.Status.SENT,
        idempotency_key="fiscal:sale:1",
    )

    # Payment with ACKED command is already fine and should be skipped.
    payment_done = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("7.00"),
        currency="EUR",
        fiscal_status=OrderPayment.FiscalStatus.CONFIRMED,
    )
    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment_done,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        status=DeviceCommand.Status.ACKED,
        idempotency_key="fiscal:sale:2",
    )

    called = []

    def fake_reconcile(*, payment_id: int):
        called.append(payment_id)
        return {"updated": True}

    monkeypatch.setattr(
        "apps.payments.tasks.reconcile_payment_fiscal_status",
        fake_reconcile,
    )

    result = reconcile_payment_fiscal_status_for_all_orgs.run(limit=10)

    assert result["processed"] == 1
    assert called == [payment_stuck.id]
