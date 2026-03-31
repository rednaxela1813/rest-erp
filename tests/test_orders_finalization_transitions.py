#tests/test_orders_finalization_transitions.py
import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_cannot_change_paid_order_back_to_draft(admin_client, payment_factory, capture_payment_api, lot_factory):
    client, user, org = admin_client

    from decimal import Decimal
    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    lot_factory(org=org, product=product, qty=Decimal("10.000"))

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
    assert r1.status_code == 201

    payment = payment_factory(order=order, org=org, amount=Decimal("5.00"))
    r2 = capture_payment_api(client, payment)
    assert r2.status_code == 200

    r3 = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": Order.STATUS_DRAFT},
        content_type="application/json",
    )
    assert r3.status_code == 400

    order.refresh_from_db()
    assert order.status == Order.STATUS_PAID

    
    
def test_admin_can_cancel_draft_order(admin_client):
    client, user, org = admin_client
    from apps.orders.models import Order

    order = Order.objects.create(org=org)

    resp = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": Order.STATUS_CANCELLED},
        content_type="application/json",
    )

    assert resp.status_code == 200

    order.refresh_from_db()
    assert order.status == Order.STATUS_CANCELLED






def test_cannot_set_paid_after_cancelled(admin_client, payment_factory, capture_payment_api, lot_factory):
    client, user, org = admin_client

    from decimal import Decimal
    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    lot_factory(org=org, product=product, qty=Decimal("10.000"))

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
    assert r1.status_code == 201

    r2 = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": Order.STATUS_CANCELLED},
        content_type="application/json",
    )
    assert r2.status_code == 200

    payment = payment_factory(order=order, org=org, amount=Decimal("5.00"))
    r3 = capture_payment_api(client, payment)
    assert r3.status_code == 400

    order.refresh_from_db()
    assert order.status == Order.STATUS_CANCELLED