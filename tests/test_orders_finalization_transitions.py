# tests/test_orders_finalization_transitions.py
from decimal import Decimal

import pytest


@pytest.mark.django_db
def test_cannot_change_paid_order_back_to_draft(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate
    from apps.payments.models import OrderPayment

    def seed_captured_payment(order: Order):
        order.refresh_from_db()
        OrderPayment.objects.create(
            org=org,
            order=order,
            tender=OrderPayment.Tender.CASH,
            status=OrderPayment.Status.CAPTURED,
            amount=order.total,
            currency="EUR",
            provider="manual",
        )

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE, stock_qty=Decimal("10.000"))
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

    r1 = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "qty": "1",
            "unit": str(unit.public_id),
            "unit_price": "5.00",
            "tax_rate": str(tax.public_id),
        },
        content_type="application/json",
    )
    assert r1.status_code == 201, r1.content

    seed_captured_payment(order)

    r2 = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": Order.STATUS_PAID},
        content_type="application/json",
    )
    assert r2.status_code == 200, r2.content

    # попытка paid -> draft должна быть запрещена
    r3 = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": Order.STATUS_DRAFT},
        content_type="application/json",
    )
    assert r3.status_code == 400
