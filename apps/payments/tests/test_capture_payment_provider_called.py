import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_capture_payment_calls_provider_and_sets_status_captured(admin_client, monkeypatch):
    client, user, org = admin_client

    from apps.orders.models import Order, OrderItem
    from apps.payments.models import OrderPayment
    from apps.payments.logic.capture_payment import capture_payment
    from apps.products.models import Product, Unit, TaxRate
    from apps.inventory.services.receive_stock import receive_stock

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Cola", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    receive_stock(org=org, product=product, initial_qty=Decimal("10.000"), unit_cost=Decimal("1.00"), label_code="LOT-COLA")

    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("2.000"),
        unit=unit,
        unit_price=Decimal("3.50"),
        tax_rate=tax,
    )

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.AUTHORIZED,
        amount=Decimal("10.00"),
        currency="EUR",
        provider="manual",
    )

    calls = {"count": 0}

    def fake_capture(*, payment, timeout_s: int):
        calls["count"] += 1
        return {"ok": True, "provider": "fake", "capture_id": "C1"}

    monkeypatch.setattr(
        "apps.payments.providers.registry.get_provider_for_payment",
        lambda p: type("P", (), {"capture": staticmethod(fake_capture)}),
    )

    capture_payment(payment=payment, actor=user)

    payment.refresh_from_db()
    assert calls["count"] == 1
    assert payment.status == OrderPayment.Status.CAPTURED
    assert payment.raw_provider_payload == {
        "ok": True,
        "provider": "fake",
        "capture_id": "C1",
    }