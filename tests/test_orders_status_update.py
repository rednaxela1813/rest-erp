#tests/test_orders_status_update.py
import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db




def test_admin_can_set_order_status_to_paid(admin_client, payment_factory, capture_payment_api, lot_factory):
    client, user, org = admin_client
    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    lot_factory(org=org, product=product, qty=Decimal("10.000"))

    resp_item = client.post(
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
    assert resp_item.status_code == 201, resp_item.content

    payment = payment_factory(order=order, org=org, amount=Decimal("5.00"))
    resp = capture_payment_api(client, payment)
    assert resp.status_code == 200, resp.content

    order.refresh_from_db()
    assert order.status == Order.STATUS_PAID
    

def test_admin_cannot_set_order_status_to_paid_directly(admin_client, lot_factory):
    client, user, org = admin_client
    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    lot_factory(org=org, product=product, qty=Decimal("10.000"))

    resp_item = client.post(
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
    assert resp_item.status_code == 201, resp_item.content

    resp = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": Order.STATUS_PAID},
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json() == {"status": ["Direct order payment is blocked. Use payment capture endpoint."]}





def test_member_cannot_change_order_status(member_client, payment_factory, capture_payment_api):
    client, user, org = member_client
    from apps.orders.models import Order

    order = Order.objects.create(org=org)

    payment = payment_factory(order=order, org=org, amount=Decimal("5.00"))
    resp = capture_payment_api(client, payment)

    assert resp.status_code == 403
