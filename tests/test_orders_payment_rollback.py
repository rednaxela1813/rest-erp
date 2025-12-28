# tests/test_orders_payment_rollback.py
from decimal import Decimal

import pytest


@pytest.mark.django_db
def test_pay_order_rolls_back_stock_if_error_occurs_midway(admin_client, monkeypatch):
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

    product_a = Product.objects.create(org=org, name="A", status="active", stock_qty=Decimal("10"))
    product_b = Product.objects.create(org=org, name="B", status="active", stock_qty=Decimal("10"))

    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("0.20"))

    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product_a.public_id),
            "unit": str(unit.public_id),
            "tax_rate": str(tax_rate.public_id),
            "qty": "2",
            "unit_price": "1.00",
        },
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp.status_code == 201, resp.content

    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product_b.public_id),
            "unit": str(unit.public_id),
            "tax_rate": str(tax_rate.public_id),
            "qty": "3",
            "unit_price": "1.00",
        },
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp.status_code == 201, resp.content

    # NEW: без captured payment мы не дойдём до списания -> monkeypatch не сработает
    seed_captured_payment(order)

    original_save = Product.save
    calls = {"count": 0}

    def exploding_save(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("DB write failed")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(Product, "save", exploding_save)

    with pytest.raises(RuntimeError, match="DB write failed"):
        client.patch(
            f"/api/v1/orders/{order.public_id}/",
            data={"status": "paid"},
            content_type="application/json",
            HTTP_X_ORG_ID=str(org.public_id),
        )

    # rollback checks
    order.refresh_from_db()
    assert order.status == Order.STATUS_DRAFT

    product_a.refresh_from_db()
    product_b.refresh_from_db()
    assert product_a.stock_qty == Decimal("10")
    assert product_b.stock_qty == Decimal("10")
