import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_order_status_events_list_returns_events_for_order(admin_client, payment_factory, capture_payment_api, lot_factory):
    client, user, org = admin_client

    from decimal import Decimal
    from apps.orders.models import Order
    from apps.products.models import Product, Unit, TaxRate

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Cola", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    lot_factory(org=org, product=product, qty=Decimal("10.000"))

    resp_item = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "unit": str(unit.public_id),
            "tax_rate": str(tax.public_id),
            "qty": "2",
            "unit_price": "3.50",
        },
        content_type="application/json",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp_item.status_code == 201, resp_item.content

    payment = payment_factory(order=order, org=org, amount=Decimal("7.00"))
    resp_pay = capture_payment_api(client, payment)
    assert resp_pay.status_code == 200, resp_pay.content

    resp = client.get(
        f"/api/v1/orders/{order.public_id}/status-events/",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp.status_code == 200, resp.content

    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    event = data[0]
    assert event["order"] == str(order.public_id)
    assert event["from_status"] == Order.STATUS_DRAFT
    assert event["to_status"] == Order.STATUS_PAID
    assert "created_at" in event
    
    
@pytest.mark.django_db
def test_order_status_events_list_is_org_scoped(admin_client, org_factory):
    client, user, org = admin_client

    from apps.orders.models import Order

    other_org = org_factory(name="Other Org")
    other_order = Order.objects.create(org=other_org)

    # пытаемся читать события чужого заказа со своим X_ORG_ID -> ожидаем 404
    resp = client.get(
        f"/api/v1/orders/{other_order.public_id}/status-events/",
        HTTP_X_ORG_ID=str(org.public_id),
    )
    assert resp.status_code == 404
