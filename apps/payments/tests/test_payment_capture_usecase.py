import pytest
from django.core.exceptions import ValidationError

pytestmark = pytest.mark.django_db


def test_capture_payment_transitions_and_creates_event(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.logic.payments import create_payment, authorize_payment, capture_payment
    from apps.payments.models import PaymentEvent

    order = Order.objects.create(org=org)

    payment = create_payment(
        order=order,
        tender="card",
        amount="12.50",
        currency="EUR",
        actor=user,
        idempotency_key="idem-cap-1",
        provider="manual",
    )

    authorize_payment(payment=payment, actor=user)
    capture_payment(payment=payment, actor=user, metadata={"rrn": "123", "receipt": "ABC"})

    payment.refresh_from_db()
    assert payment.status == "captured"

    ev = PaymentEvent.objects.filter(payment=payment, action="capture").get()
    assert ev.org_id == org.id
    assert ev.actor_id == user.id
    assert ev.from_status == "authorized"
    assert ev.to_status == "captured"
    assert ev.metadata["rrn"] == "123"


def test_cannot_capture_pending(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.logic.payments import create_payment, capture_payment

    order = Order.objects.create(org=org)

    payment = create_payment(
        order=order,
        tender="card",
        amount="10.00",
        currency="EUR",
        actor=user,
        idempotency_key="idem-cap-2",
        provider="manual",
    )

    with pytest.raises(ValidationError):
        capture_payment(payment=payment, actor=user)


def test_cannot_capture_twice(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.logic.payments import create_payment, authorize_payment, capture_payment

    order = Order.objects.create(org=org)

    payment = create_payment(
        order=order,
        tender="card",
        amount="10.00",
        currency="EUR",
        actor=user,
        idempotency_key="idem-cap-3",
        provider="manual",
    )

    authorize_payment(payment=payment, actor=user)
    capture_payment(payment=payment, actor=user)

    with pytest.raises(ValidationError):
        capture_payment(payment=payment, actor=user)
