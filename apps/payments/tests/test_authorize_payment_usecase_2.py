# tests/test_authorize_payment_usecase.py
import pytest
from decimal import Decimal
from rest_framework.exceptions import ValidationError


@pytest.mark.django_db
def test_authorize_payment_transitions_to_authorized_and_creates_event(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.models import OrderPayment, PaymentEvent
    from apps.payments.logic.authorize_payment import authorize_payment

    order = Order.objects.create(org=org)

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.PENDING,
        amount=Decimal("9.99"),
        currency="EUR",
        provider="manual",
    )

    authorized = authorize_payment(payment=payment, actor=user)

    authorized.refresh_from_db()
    assert authorized.status == OrderPayment.Status.AUTHORIZED

    ev = PaymentEvent.objects.filter(payment=authorized).order_by("-created_at").first()
    assert ev is not None
    assert ev.action == "authorize"
    assert ev.from_status == OrderPayment.Status.PENDING
    assert ev.to_status == OrderPayment.Status.AUTHORIZED
    assert ev.actor_id == user.id


@pytest.mark.django_db
def test_authorize_payment_is_strict_and_fails_if_already_authorized(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.models import OrderPayment
    from apps.payments.logic.authorize_payment import authorize_payment

    order = Order.objects.create(org=org)

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.AUTHORIZED,
        amount=Decimal("10.00"),
        currency="EUR",
        provider="manual",
    )

    with pytest.raises(ValidationError) as e:
        authorize_payment(payment=payment, actor=user)

    assert e.value.detail == {"status": ["Payment is already authorized."]}


@pytest.mark.django_db
def test_authorize_payment_uses_row_lock_select_for_update(admin_client, monkeypatch):
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

    from django.db.models.query import QuerySet

    original = QuerySet.select_for_update
    called = {"count": 0}

    def spy_select_for_update(self, *args, **kwargs):
        if getattr(self, "model", None) is OrderPayment:
            called["count"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "select_for_update", spy_select_for_update)

    authorize_payment(payment=payment, actor=user)

    assert called["count"] >= 1
