from decimal import Decimal

import pytest

from apps.orders.models import Order
from apps.payments.models import DeviceCommand, OrderPayment
from apps.payments.tasks import reconcile_payment_capture, reconcile_payment_fiscal_status


@pytest.mark.django_db
def test_reconcile_payment_capture_confirms_for_manual_provider(org_factory):
    org = org_factory()
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
        capture_status=OrderPayment.CaptureStatus.PENDING,
    )

    result = reconcile_payment_capture.run(payment_id=payment.id)

    payment.refresh_from_db()
    assert result["updated"] is True
    assert payment.capture_status == OrderPayment.CaptureStatus.CONFIRMED


@pytest.mark.django_db
def test_reconcile_payment_capture_skips_when_provider_missing(org_factory, monkeypatch):
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

    class DummyProvider:
        def capture_status(self, *, payment, timeout_s: int):
            raise NotImplementedError

    monkeypatch.setattr("apps.payments.providers.registry.get_provider_for_payment", lambda _: DummyProvider())

    result = reconcile_payment_capture.run(payment_id=payment.id)
    assert result["updated"] is False
    assert result["reason"] == "not_supported"


@pytest.mark.django_db
def test_reconcile_payment_fiscal_status_marks_confirmed(org_factory):
    org = org_factory()
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
        fiscal_status=OrderPayment.FiscalStatus.PENDING,
    )

    DeviceCommand.objects.create(
        org=org,
        order=order,
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        status=DeviceCommand.Status.ACKED,
        idempotency_key="fiscal:1",
    )

    result = reconcile_payment_fiscal_status.run(payment_id=payment.id)

    payment.refresh_from_db()
    assert result["updated"] is True
    assert payment.fiscal_status == OrderPayment.FiscalStatus.CONFIRMED
