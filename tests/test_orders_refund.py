from decimal import Decimal

import pytest

from apps.orders.models import Order, OrderItem
from apps.payments.models import DeviceCommand, FiscalReceipt
from apps.products.models import Product, TaxRate, Unit


@pytest.mark.django_db
def test_admin_can_refund_paid_order(admin_client, payment_factory, capture_payment_api):
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
        stock_qty=Decimal("10.000"),
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

    payment = payment_factory(order=order, org=org, amount=Decimal("5.00"))
    resp_pay = capture_payment_api(client, payment)
    assert resp_pay.status_code == 200, resp_pay.content

    refund = client.post(f"/api/v1/orders/{order.public_id}/refund/")
    assert refund.status_code == 200, refund.content

    order.refresh_from_db()
    assert order.status == Order.STATUS_CANCELLED

    receipt = FiscalReceipt.objects.get(order=order, receipt_type=FiscalReceipt.Type.REFUND)
    assert receipt.payment_id == payment.id

    refund_commands = DeviceCommand.objects.filter(
        payment=payment, command_type=DeviceCommand.Type.FISCALIZE_REFUND
    )
    assert refund_commands.count() == 1


@pytest.mark.django_db
def test_member_cannot_refund_paid_order(member_client, payment_factory, capture_payment_api):
    client, user, org = member_client

    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    product = Product.objects.create(
        org=org,
        name="Burger",
        status=Product.STATUS_ACTIVE,
        unit=unit,
        tax_rate=tax,
        unit_price=Decimal("5.00"),
        stock_qty=Decimal("10.000"),
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

    payment = payment_factory(order=order, org=org, amount=Decimal("5.00"))
    resp_pay = capture_payment_api(client, payment)
    assert resp_pay.status_code == 403, resp_pay.content

    refund = client.post(f"/api/v1/orders/{order.public_id}/refund/")
    assert refund.status_code == 403
