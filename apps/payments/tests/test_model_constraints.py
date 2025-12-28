import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_external_id_unique_per_org(admin_client, org_factory):
    client, user, org1 = admin_client

    from apps.orders.models import Order
    from apps.payments.models import OrderPayment

    org2 = org_factory(name="Org 2")

    order1 = Order.objects.create(org=org1)
    order2 = Order.objects.create(org=org2)

    OrderPayment.objects.create(
        org=org1,
        order=order1,
        tender="cash",
        status="pending",
        amount=Decimal("1.00"),
        currency="EUR",
        external_id="ext-1",
        provider="manual",
    )

    # В другой org такой же external_id допустим
    OrderPayment.objects.create(
        org=org2,
        order=order2,
        tender="cash",
        status="pending",
        amount=Decimal("1.00"),
        currency="EUR",
        external_id="ext-1",
        provider="manual",
    )

    assert OrderPayment.objects.count() == 2


def test_external_id_must_be_unique_within_same_org(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.models import OrderPayment
    from django.db import IntegrityError

    order = Order.objects.create(org=org)

    OrderPayment.objects.create(
        org=org,
        order=order,
        tender="cash",
        status="pending",
        amount=Decimal("1.00"),
        currency="EUR",
        external_id="ext-dup",
        provider="manual",
    )

    with pytest.raises(IntegrityError):
        OrderPayment.objects.create(
            org=org,
            order=order,
            tender="cash",
            status="pending",
            amount=Decimal("2.00"),
            currency="EUR",
            external_id="ext-dup",  # дубликат в той же org
            provider="manual",
        )
