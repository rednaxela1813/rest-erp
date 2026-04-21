import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_capture_payment_uses_usecase_function(admin_client, payment_factory, capture_payment_api, monkeypatch):
    client, user, org = admin_client

    from apps.orders.models import Order

    order = Order.objects.create(org=org)
    payment = payment_factory(order=order, org=org, amount=Decimal("7.00"))

    called = {"value": False}

    def fake_capture_payment(*, payment, actor=None, timeout_s: int = 30):
        called["value"] = True
        return payment

    import apps.payments.api_views as api_views

    monkeypatch.setattr(api_views, "capture_payment", fake_capture_payment)

    resp = capture_payment_api(client, payment)
    assert resp.status_code == 200
    assert called["value"] is True
