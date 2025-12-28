import pytest
from django.core.exceptions import ValidationError

pytestmark = pytest.mark.django_db


def test_authorize_payment_transitions_and_creates_event(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.logic.payments import create_payment, authorize_payment
    from apps.payments.models import PaymentEvent

    order = Order.objects.create(org=org)

    payment = create_payment(
        order=order,
        tender="card",
        amount="10.00",
        currency="EUR",
        actor=user,
        idempotency_key="idem-auth-1",
        provider="manual",
    )

    authorize_payment(payment=payment, actor=user, metadata={"source": "pos"})

    payment.refresh_from_db()
    assert payment.status == "authorized"

    # проверяем, что создалось событие authorize (плюс create уже есть)
    ev = PaymentEvent.objects.filter(payment=payment, action="authorize").get()
    assert ev.org_id == org.id
    assert ev.actor_id == user.id
    assert ev.from_status == "pending"
    assert ev.to_status == "authorized"
    assert ev.metadata["source"] == "pos"


def test_cannot_authorize_twice(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.logic.payments import create_payment, authorize_payment

    order = Order.objects.create(org=org)

    payment = create_payment(
        order=order,
        tender="card",
        amount="10.00",
        currency="EUR",
        actor=user,
        idempotency_key="idem-auth-2",
        provider="manual",
    )

    authorize_payment(payment=payment, actor=user)

    with pytest.raises(ValidationError):
        authorize_payment(payment=payment, actor=user)
