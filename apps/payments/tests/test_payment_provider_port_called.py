# tests/test_payment_provider_port_called.py
import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_authorize_payment_calls_provider_and_persists_raw_payload(admin_client, monkeypatch):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.models import OrderPayment
    from apps.payments.logic.authorize_payment import authorize_payment

    order = Order.objects.create(org=org)

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.PENDING,
        amount=Decimal("10.00"),
        currency="EUR",
        provider="manual",
    )

    calls = {"count": 0, "seen": None}

    def fake_authorize(*, payment, timeout_s: int):
        calls["count"] += 1
        calls["seen"] = payment.public_id
        return {"ok": True, "provider": "fake", "auth_code": "A1"}

    # ВАЖНО: путь подставь под фактический модуль, который создадим ниже
    monkeypatch.setattr(
        "apps.payments.providers.registry.get_provider_for_payment",
        lambda p: type("P", (), {"authorize": staticmethod(fake_authorize)}),
    )

    authorize_payment(payment=payment, actor=user)

    payment.refresh_from_db()
    assert calls["count"] == 1
    assert calls["seen"] == payment.public_id
    assert payment.raw_provider_payload == {"ok": True, "provider": "fake", "auth_code": "A1"}
