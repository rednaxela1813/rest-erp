from decimal import Decimal

import pytest

from apps.orders.models import Order, OrderItem
from apps.payments.models import FiscalReceipt
from apps.products.models import Product, TaxRate, Unit

from apps.inventory.services.receive_stock import receive_stock


@pytest.mark.django_db
def test_capture_payment_creates_fiscal_receipt_for_card(admin_client, payment_factory, capture_payment_api):
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
    receive_stock(org=org, product=product, initial_qty=Decimal("10.000"), unit_cost=Decimal("1.00"), label_code=f"LOT-{product.name.upper()}")

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

    payment = payment_factory(order=order, org=org, amount=Decimal("5.00"))
    resp = capture_payment_api(client, payment)
    assert resp.status_code == 200, resp.content

    # Payment instance is stale after API call; refresh to get updated provider payload.
    payment.refresh_from_db()

    receipt = FiscalReceipt.objects.get(payment=payment)
    assert receipt.receipt_type == FiscalReceipt.Type.SALE
    assert receipt.order_id == order.id
    assert receipt.total == payment.amount
    assert receipt.tax_total == order.tax_total
    assert receipt.currency == payment.currency
    assert receipt.raw_payload == payment.raw_provider_payload
    assert receipt.uid is not None
