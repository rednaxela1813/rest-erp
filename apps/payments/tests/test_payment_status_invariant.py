import pytest
from decimal import Decimal
from django.core.exceptions import ValidationError

pytestmark = pytest.mark.django_db


def test_cannot_change_payment_status_directly(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.models import OrderPayment

    order = Order.objects.create(org=org)

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender="cash",
        status="pending",
        amount=Decimal("10.00"),
        currency="EUR",
        provider="manual",
    )

    # Прямая смена статуса запрещена (только через use-case)
    payment.status = "captured"
    with pytest.raises(ValidationError):
        payment.save()
