import pytest
from decimal import Decimal
from datetime import timedelta

from django.utils import timezone


pytestmark = pytest.mark.django_db


def _create_kitchen_ticket(*, org, order, product, qty=Decimal("1.000"), status="pending"):
    from apps.orders.models import KitchenTicket

    return KitchenTicket.objects.create(
        org=org,
        order=order,
        product=product,
        qty=qty,
        status=status,
    )


def test_paid_order_with_prep_product_creates_kitchen_ticket(
    admin_client, payment_factory, capture_payment_api
):
    client, user, org = admin_client

    from apps.orders.models import KitchenTicket, Order
    from apps.products.models import Product, TaxRate, Unit

    product = Product.objects.create(
        org=org,
        name="Pizza",
        status=Product.STATUS_ACTIVE,
        requires_preparation=True,
    )
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

    order = Order.objects.create(org=org)
    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "qty": "2",
            "unit": str(unit.public_id),
            "unit_price": "3.95",
            "tax_rate": str(tax.public_id),
        },
        content_type="application/json",
    )
    assert resp.status_code == 201

    payment = payment_factory(order=order, org=org, amount=Decimal("7.90"))
    pay_resp = capture_payment_api(client, payment)
    assert pay_resp.status_code == 200

    product.refresh_from_db()
    assert product.stock_qty is None

    ticket = KitchenTicket.objects.filter(order=order, product=product).first()
    assert ticket is not None
    assert ticket.qty == Decimal("2.000")
    assert ticket.status == KitchenTicket.Status.PENDING


def test_kitchen_ticket_list_defaults_to_pending(owner_client):
    client, user, org = owner_client

    from apps.orders.models import Order
    from apps.products.models import Product

    order = Order.objects.create(org=org)
    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)

    _create_kitchen_ticket(org=org, order=order, product=product, status="pending")
    _create_kitchen_ticket(org=org, order=order, product=product, status="in_progress")

    resp = client.get("/api/v1/kitchen/tickets/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "pending"


def test_kitchen_ticket_list_filters_statuses(owner_client):
    client, user, org = owner_client

    from apps.orders.models import Order
    from apps.products.models import Product

    order = Order.objects.create(org=org)
    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)

    _create_kitchen_ticket(org=org, order=order, product=product, status="pending")
    _create_kitchen_ticket(org=org, order=order, product=product, status="in_progress")

    resp = client.get("/api/v1/kitchen/tickets/?status=pending,in_progress")
    assert resp.status_code == 200
    data = resp.json()
    assert {item["status"] for item in data} == {"pending", "in_progress"}


def test_kitchen_ticket_claims_next_in_fifo_order(admin_client):
    client, user, org = admin_client

    from apps.orders.models import KitchenTicket, Order
    from apps.products.models import Product

    order = Order.objects.create(org=org)
    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)

    first = _create_kitchen_ticket(org=org, order=order, product=product, status="pending")
    second = _create_kitchen_ticket(org=org, order=order, product=product, status="pending")

    now = timezone.now()
    KitchenTicket.objects.filter(pk=first.pk).update(created_at=now - timedelta(minutes=5))
    KitchenTicket.objects.filter(pk=second.pk).update(created_at=now - timedelta(minutes=1))

    resp1 = client.post("/api/v1/kitchen/tickets/next/", content_type="application/json")
    assert resp1.status_code == 200
    assert resp1.json()["public_id"] == str(first.public_id)

    first.refresh_from_db()
    assert first.status == KitchenTicket.Status.IN_PROGRESS

    resp2 = client.post("/api/v1/kitchen/tickets/next/", content_type="application/json")
    assert resp2.status_code == 200
    assert resp2.json()["public_id"] == str(second.public_id)

    resp3 = client.post("/api/v1/kitchen/tickets/next/", content_type="application/json")
    assert resp3.status_code == 204


def test_kitchen_ticket_update_status(admin_client):
    client, user, org = admin_client

    from apps.orders.models import KitchenTicket, Order
    from apps.products.models import Product

    order = Order.objects.create(org=org)
    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)
    ticket = _create_kitchen_ticket(org=org, order=order, product=product, status="pending")

    resp = client.patch(
        f"/api/v1/kitchen/tickets/{ticket.public_id}/",
        data={"status": "done"},
        content_type="application/json",
    )
    assert resp.status_code == 200

    ticket.refresh_from_db()
    assert ticket.status == KitchenTicket.Status.DONE


def test_kitchen_ticket_claim_next_with_queue_returns_lists(admin_client):
    client, user, org = admin_client

    from apps.orders.models import KitchenTicket, Order
    from apps.products.models import Product

    order = Order.objects.create(org=org)
    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)

    first = _create_kitchen_ticket(org=org, order=order, product=product, status="pending")
    second = _create_kitchen_ticket(org=org, order=order, product=product, status="pending")

    resp = client.post("/api/v1/kitchen/tickets/next-with-queue/", content_type="application/json")
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["claimed"]["public_id"] == str(first.public_id)
    assert payload["pending"][0]["public_id"] == str(second.public_id)
    assert payload["in_progress"][0]["public_id"] == str(first.public_id)

    first.refresh_from_db()
    assert first.status == KitchenTicket.Status.IN_PROGRESS
