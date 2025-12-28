import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_pay_order_uses_usecase_function(admin_client, monkeypatch):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate

    order = Order.objects.create(org=org)

    product = Product.objects.create(
        org=org,
        name="Cola",
        status="active",
        stock_qty=Decimal("10"),
    )
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("0.20"))

    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "unit": str(unit.public_id),
            "tax_rate": str(tax_rate.public_id),
            "qty": "2",
            "unit_price": "3.50",
        },
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp.status_code == 201

    called = {"value": False}

    
    def fake_pay_order(*, order):
        called["value"] = True
        # минимальная имитация успеха, но с соблюдением инварианта модели:
        order.status = "paid"
        order._status_change_allowed = True
        order.save(update_fields=["status"])
        return order


    import apps.orders.api_views as api_views
    monkeypatch.setattr(api_views, "pay_order", fake_pay_order)

    resp2 = client.patch(
        f"/api/v1/orders/{order.public_id}/",
        data={"status": "paid"},
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp2.status_code == 200
    assert called["value"] is True
