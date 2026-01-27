from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from apps.orders.models import Order
from apps.payments.logic.start_payment import start_payment
from apps.payments.models import OrderPayment


@pytest.mark.django_db
def test_start_payment_is_idempotent_for_same_order(org_factory):
    org = org_factory()
    order = Order.objects.create(org=org)

    payment_1 = start_payment(
        order=order,
        tender=OrderPayment.Tender.CARD,
        amount=Decimal("10.00"),
        currency="EUR",
        idempotency_key="pay-123",
    )
    payment_2 = start_payment(
        order=order,
        tender=OrderPayment.Tender.CARD,
        amount=Decimal("10.00"),
        currency="EUR",
        idempotency_key="pay-123",
    )

    assert payment_1.id == payment_2.id
    assert OrderPayment.objects.filter(org=org, idempotency_key="pay-123").count() == 1


@pytest.mark.django_db
def test_start_payment_rejects_idempotency_key_reuse_for_other_order(org_factory):
    org = org_factory()
    order_1 = Order.objects.create(org=org)
    order_2 = Order.objects.create(org=org)

    start_payment(
        order=order_1,
        tender=OrderPayment.Tender.CARD,
        amount=Decimal("10.00"),
        currency="EUR",
        idempotency_key="pay-456",
    )

    with pytest.raises(ValidationError) as exc:
        start_payment(
            order=order_2,
            tender=OrderPayment.Tender.CARD,
            amount=Decimal("10.00"),
            currency="EUR",
            idempotency_key="pay-456",
        )

    assert exc.value.detail == {"idempotency_key": ["Idempotency key already used."]}
