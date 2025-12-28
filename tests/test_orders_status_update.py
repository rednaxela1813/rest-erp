#tests/test_orders_status_update.py
import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db




def test_admin_can_set_order_status_to_paid(admin_client):
    client, user, org = admin_client
    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate

    order = Order.objects.create(org=org)  # draft

    # добавим 1 item, иначе paid запрещён
    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE, stock_qty=Decimal("10.000"))
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

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
    assert resp.status_code == 200, resp.content

    order.refresh_from_db()
    assert order.status == Order.STATUS_PAID





def test_member_cannot_change_order_status(member_client):
    client, user, org = member_client
    from apps.orders.models import Order

    order = Order.objects.create(org=org)

    resp = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": Order.STATUS_PAID},
        content_type="application/json",
    )

    assert resp.status_code == 403
