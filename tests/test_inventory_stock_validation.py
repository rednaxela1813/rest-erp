import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_cannot_pay_order_if_insufficient_stock(admin_client, payment_factory, capture_payment_api, lot_factory):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate
    from apps.inventory.models import StockLot

    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    lot_factory(org=org, product=product, qty=Decimal("1.000"))

    order = Order.objects.create(org=org)
    r1 = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "qty": "2",
            "unit": str(unit.public_id),
            "unit_price": "5.00",
            "tax_rate": str(tax.public_id),
        },
        content_type="application/json",
    )
    assert r1.status_code == 201

    payment = payment_factory(order=order, org=org, amount=Decimal("10.00"))
    r2 = capture_payment_api(client, payment)
    assert r2.status_code == 400

    order.refresh_from_db()
    assert order.status == Order.STATUS_DRAFT

    lot = StockLot.objects.get(org=org, product=product)
    assert lot.remaining_qty == Decimal("1.000")
