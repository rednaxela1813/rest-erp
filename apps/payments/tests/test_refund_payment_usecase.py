# tests/test_refund_payment_usecase.py
import pytest
from decimal import Decimal
from rest_framework.exceptions import ValidationError


@pytest.mark.django_db
def test_refund_payment_transitions_to_refunded_and_creates_event(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.models import OrderPayment, PaymentEvent
    from apps.payments.logic.refund_payment import refund_payment

    order = Order.objects.create(org=org)

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("10.00"),
        currency="EUR",
        provider="manual",
    )

    refunded = refund_payment(payment=payment, actor=user)

    refunded.refresh_from_db()
    assert refunded.status == OrderPayment.Status.REFUNDED

    ev = PaymentEvent.objects.filter(payment=refunded).order_by("-created_at").first()
    assert ev is not None
    assert ev.action == "refund"
    assert ev.from_status == OrderPayment.Status.CAPTURED
    assert ev.to_status == OrderPayment.Status.REFUNDED
    assert ev.actor_id == user.id


@pytest.mark.django_db
def test_refund_payment_is_strict_and_fails_if_already_refunded(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.models import OrderPayment
    from apps.payments.logic.refund_payment import refund_payment

    order = Order.objects.create(org=org)

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.REFUNDED,
        amount=Decimal("10.00"),
        currency="EUR",
        provider="manual",
    )

    with pytest.raises(ValidationError) as e:
        refund_payment(payment=payment, actor=user)

    assert e.value.detail == {"status": ["Payment is already refunded."]}


@pytest.mark.django_db
@pytest.mark.parametrize("start_status", ["pending", "authorized", "voided", "failed"])
def test_refund_payment_fails_if_not_captured(admin_client, start_status):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.models import OrderPayment
    from apps.payments.logic.refund_payment import refund_payment

    order = Order.objects.create(org=org)

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=start_status,
        amount=Decimal("10.00"),
        currency="EUR",
        provider="manual",
    )

    with pytest.raises(ValidationError) as e:
        refund_payment(payment=payment, actor=user)

    assert e.value.detail == {"status": ["Invalid status transition."]}


@pytest.mark.django_db
def test_refund_payment_uses_row_lock_select_for_update(admin_client, monkeypatch):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.models import OrderPayment
    from apps.payments.logic.refund_payment import refund_payment

    order = Order.objects.create(org=org)

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("10.00"),
        currency="EUR",
        provider="manual",
    )

    from django.db.models.query import QuerySet

    original = QuerySet.select_for_update
    called = {"count": 0}

    def spy_select_for_update(self, *args, **kwargs):
        if getattr(self, "model", None) is OrderPayment:
            called["count"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "select_for_update", spy_select_for_update)

    refund_payment(payment=payment, actor=user)

    assert called["count"] >= 1
