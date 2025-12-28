import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_order_item_create_unit_from_other_org_returns_400(admin_client, org_factory, member_factory):
    client, user, org_a = admin_client

    from apps.orders.models import Order
    from apps.products.models import Unit, TaxRate, Product

    order = Order.objects.create(org=org_a)

    # product в org A (валидный)
    product = Product.objects.create(org=org_a, name="Burger", status=Product.STATUS_ACTIVE)

    # org B (чужая) + unit оттуда
    org_b = org_factory(name="Foreign Org")
    foreign_unit = Unit.objects.create(org=org_b, name="pcs", status=Unit.STATUS_ACTIVE)

    # tax в org A (валидный)
    tax = TaxRate.objects.create(org=org_a, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "qty": "1",
            "unit": str(foreign_unit.public_id),  # чужая org
            "unit_price": "5.00",
            "tax_rate": str(tax.public_id),
        },
        content_type="application/json",
    )

    assert resp.status_code == 400
    data = resp.json()
    assert "unit" in data


def test_order_item_create_taxrate_from_other_org_returns_400(admin_client, org_factory):
    client, user, org_a = admin_client

    from apps.orders.models import Order
    from apps.products.models import Unit, TaxRate, Product

    order = Order.objects.create(org=org_a)

    product = Product.objects.create(org=org_a, name="Burger", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org_a, name="pcs", status=Unit.STATUS_ACTIVE)

    org_b = org_factory(name="Foreign Org")
    foreign_tax = TaxRate.objects.create(
        org=org_b, name="DPH 10%", rate=Decimal("10.00"), status=TaxRate.STATUS_ACTIVE
    )

    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "qty": "1",
            "unit": str(unit.public_id),
            "unit_price": "5.00",
            "tax_rate": str(foreign_tax.public_id),  # чужая org
        },
        content_type="application/json",
    )

    assert resp.status_code == 400
    data = resp.json()
    assert "tax_rate" in data


def test_order_item_create_archived_unit_returns_400(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Unit, TaxRate, Product

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)
    archived_unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ARCHIVED)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "qty": "1",
            "unit": str(archived_unit.public_id),  # archived
            "unit_price": "5.00",
            "tax_rate": str(tax.public_id),
        },
        content_type="application/json",
    )

    assert resp.status_code == 400
    data = resp.json()
    assert "unit" in data


def test_order_item_create_archived_taxrate_returns_400(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Unit, TaxRate, Product

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    archived_tax = TaxRate.objects.create(
        org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ARCHIVED
    )

    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "qty": "1",
            "unit": str(unit.public_id),
            "unit_price": "5.00",
            "tax_rate": str(archived_tax.public_id),  # archived
        },
        content_type="application/json",
    )

    assert resp.status_code == 400
    data = resp.json()
    assert "tax_rate" in data


def test_order_item_create_in_foreign_order_returns_404(admin_client, org_factory):
    client, user, org_a = admin_client

    from apps.orders.models import Order
    from apps.products.models import Unit, TaxRate, Product

    # org B + order там
    org_b = org_factory(name="Foreign Org")
    foreign_order = Order.objects.create(org=org_b)

    # Валидные product/unit/tax в org A (текущая активная org)
    product = Product.objects.create(org=org_a, name="Burger", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org_a, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org_a, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

    resp = client.post(
        f"/api/v1/orders/{foreign_order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "qty": "1",
            "unit": str(unit.public_id),
            "unit_price": "5.00",
            "tax_rate": str(tax.public_id),
        },
        content_type="application/json",
    )

    assert resp.status_code == 404
