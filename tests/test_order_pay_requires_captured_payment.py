# tests/test_order_pay_requires_captured_payment.py
from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

pytestmark = pytest.mark.django_db


def test_pay_order_requires_captured_payment(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate
    from apps.orders.logic.pay_order import pay_order

    order = Order.objects.create(org=org)

    product = Product.objects.create(
        org=org,
        name="P1",
        status=Product.STATUS_ACTIVE,
        stock_qty=Decimal("10.00"),
    )
    unit = Unit.objects.create(org=org, name="pcs")
    vat = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("0.20"))

    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "unit": str(unit.public_id),
            "tax_rate": str(vat.public_id),
            "qty": "1",
            "unit_price": "10.00",
        },
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp.status_code == 201, resp.content

    order.refresh_from_db()

    with pytest.raises(ValidationError):
        pay_order(order=order, actor=user)
