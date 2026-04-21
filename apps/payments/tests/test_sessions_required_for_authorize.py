import pytest
from decimal import Decimal
from rest_framework.exceptions import ValidationError


@pytest.mark.django_db
def test_authorize_payment_requires_open_session(admin_client):
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

    with pytest.raises(ValidationError) as e:
        authorize_payment(payment=payment, actor=user, terminal=None, session=None)

    assert e.value.detail == {"session": ["Open cashier session is required."]}
