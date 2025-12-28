import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_create_payment_creates_payment_and_event(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.logic.payments import create_payment
    from apps.payments.models import OrderPayment, PaymentEvent

    order = Order.objects.create(org=org)

    payment = create_payment(
        order=order,
        tender="cash",
        amount=Decimal("10.00"),
        currency="EUR",
        actor=user,
        idempotency_key="idem-1",
        external_id="ext-1",
        provider="manual",
        metadata={"note": "first payment"},
    )

    assert payment.org_id == org.id
    assert payment.order_id == order.id
    assert payment.tender == "cash"
    assert payment.status == "pending"
    assert payment.amount == Decimal("10.00")
    assert payment.currency == "EUR"
    assert payment.idempotency_key == "idem-1"
    assert payment.external_id == "ext-1"
    assert payment.provider == "manual"
    assert payment.raw_provider_payload is None

    assert OrderPayment.objects.count() == 1
    assert PaymentEvent.objects.count() == 1

    ev = PaymentEvent.objects.get()
    assert ev.org_id == org.id
    assert ev.payment_id == payment.id
    assert ev.actor_id == user.id
    assert ev.from_status is None
    assert ev.to_status == "pending"
    assert ev.action == "create"
    assert ev.metadata["note"] == "first payment"


def test_create_payment_is_idempotent_per_org(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.logic.payments import create_payment
    from apps.payments.models import OrderPayment, PaymentEvent

    order = Order.objects.create(org=org)

    p1 = create_payment(
        order=order,
        tender="cash",
        amount=Decimal("10.00"),
        currency="EUR",
        actor=user,
        idempotency_key="idem-1",
        provider="manual",
    )

    p2 = create_payment(
        order=order,
        tender="cash",
        amount=Decimal("10.00"),
        currency="EUR",
        actor=user,
        idempotency_key="idem-1",  # тот же ключ
        provider="manual",
    )

    assert p2.id == p1.id
    assert OrderPayment.objects.count() == 1
    # В первой итерации: повторный вызов НЕ должен плодить аудит-события
    assert PaymentEvent.objects.count() == 1


def test_idempotency_key_is_unique_per_org_but_can_repeat_in_other_org(org_factory, django_user_model):
    from apps.orders.models import Order
    from apps.payments.logic.payments import create_payment
    from apps.payments.models import OrderPayment

    user = django_user_model.objects.create_user(email="u@example.com", password="x")

    org1 = org_factory(name="Org 1")
    org2 = org_factory(name="Org 2")

    order1 = Order.objects.create(org=org1)
    order2 = Order.objects.create(org=org2)

    p1 = create_payment(
        order=order1,
        tender="cash",
        amount=Decimal("1.00"),
        currency="EUR",
        actor=user,
        idempotency_key="idem-same",
        provider="manual",
    )
    p2 = create_payment(
        order=order2,
        tender="cash",
        amount=Decimal("2.00"),
        currency="EUR",
        actor=user,
        idempotency_key="idem-same",  # тот же ключ, но другая org
        provider="manual",
    )

    assert p1.id != p2.id
    assert OrderPayment.objects.count() == 2
