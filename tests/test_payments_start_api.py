from decimal import Decimal

import pytest

from apps.orders.models import Order, OrderItem
from apps.products.models import Product, TaxRate, Unit


@pytest.mark.django_db
def test_payment_start_is_idempotent(admin_client):
    client, user, org = admin_client

    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    product = Product.objects.create(
        org=org,
        name="Burger",
        status=Product.STATUS_ACTIVE,
        unit=unit,
        tax_rate=tax,
        unit_price=Decimal("5.00"),
    )

    order = Order.objects.create(org=org)
    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("1.000"),
        unit=unit,
        unit_price=Decimal("5.00"),
        tax_rate=tax,
    )
    order.recompute_totals()
    order.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])

    payload = {
        "order": str(order.public_id),
        "tender": "card",
        "amount": "5.00",
        "currency": "EUR",
        "idempotency_key": "start-1",
    }

    resp_1 = client.post("/api/v1/payments/start/", data=payload, content_type="application/json")
    assert resp_1.status_code == 200, resp_1.content

    resp_2 = client.post("/api/v1/payments/start/", data=payload, content_type="application/json")
    assert resp_2.status_code == 200, resp_2.content

    assert resp_1.json()["payment"] == resp_2.json()["payment"]
