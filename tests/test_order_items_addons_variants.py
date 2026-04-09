import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_order_totals_include_addons(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order, OrderItem, OrderItemAddon
    from apps.products.models import Product, ProductAddon, ProductVariant, TaxRate, Unit

    order = Order.objects.create(org=org)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    product = Product.objects.create(org=org, name="Pizza", status=Product.STATUS_ACTIVE)
    variant = ProductVariant.objects.create(
        product=product,
        name="L",
        unit_price=Decimal("12.00"),
        status=ProductVariant.STATUS_ACTIVE,
    )
    addon = ProductAddon.objects.create(
        product=product,
        name="Extra cheese",
        price=Decimal("1.50"),
        status=ProductAddon.STATUS_ACTIVE,
    )

    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "variant": str(variant.public_id),
            "addons": [str(addon.public_id)],
            "note": "No onion",
            "qty": "2",
            "unit": str(unit.public_id),
            "unit_price": "12.00",
            "tax_rate": str(tax.public_id),
        },
        content_type="application/json",
    )

    assert resp.status_code == 201, resp.content

    order.refresh_from_db()
    assert order.subtotal == Decimal("27.00")
    assert order.total == Decimal("27.00")
    assert order.tax_total == Decimal("4.50")

    item = OrderItem.objects.get(order=order)
    assert item.variant_id == variant.id
    assert item.variant_name == "L"
    assert item.note == "No onion"

    addon_item = OrderItemAddon.objects.get(order_item__order=order)
    assert addon_item.name == "Extra cheese"
    assert addon_item.price == Decimal("1.50")


def test_order_item_rejects_variant_from_another_product(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, ProductVariant, TaxRate, Unit

    order = Order.objects.create(org=org)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)
    other_product = Product.objects.create(org=org, name="Pizza", status=Product.STATUS_ACTIVE)
    foreign_variant = ProductVariant.objects.create(
        product=other_product,
        name="XL",
        unit_price=Decimal("15.00"),
        status=ProductVariant.STATUS_ACTIVE,
    )

    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "variant": str(foreign_variant.public_id),
            "qty": "1",
            "unit": str(unit.public_id),
            "unit_price": "10.00",
            "tax_rate": str(tax.public_id),
        },
        content_type="application/json",
    )

    assert resp.status_code == 400, resp.content
    assert resp.json()["variant"] == ["Invalid variant."]


def test_order_item_rejects_invalid_addon(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.products.models import Product, ProductAddon, TaxRate, Unit

    order = Order.objects.create(org=org)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    product = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE)
    other_product = Product.objects.create(org=org, name="Pizza", status=Product.STATUS_ACTIVE)
    foreign_addon = ProductAddon.objects.create(
        product=other_product,
        name="Extra cheese",
        price=Decimal("1.50"),
        status=ProductAddon.STATUS_ACTIVE,
    )

    resp = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={
            "product": str(product.public_id),
            "addons": [str(foreign_addon.public_id)],
            "qty": "1",
            "unit": str(unit.public_id),
            "unit_price": "10.00",
            "tax_rate": str(tax.public_id),
        },
        content_type="application/json",
    )

    assert resp.status_code == 400, resp.content
    assert resp.json()["addons"] == ["Invalid addons."]
