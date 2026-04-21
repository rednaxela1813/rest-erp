from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from apps.orders.logic.create_order_item import create_order_item
from apps.products.models import Product, ProductAddon, ProductVariant, TaxRate, Unit


pytestmark = pytest.mark.django_db


def test_create_order_item_resolves_related_objects(org_factory):
    org = org_factory()
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    product = Product.objects.create(org=org, name="Pizza", status=Product.STATUS_ACTIVE)
    variant = ProductVariant.objects.create(
        product=product,
        name="XL",
        unit_price=Decimal("12.00"),
        status=ProductVariant.STATUS_ACTIVE,
    )
    addon = ProductAddon.objects.create(
        product=product,
        name="Extra cheese",
        price=Decimal("1.50"),
        status=ProductAddon.STATUS_ACTIVE,
    )

    validated = create_order_item(
        {
            "product": product.public_id,
            "unit": unit.public_id,
            "tax_rate": tax.public_id,
            "variant": variant.public_id,
            "addons": [addon.public_id],
            "qty": Decimal("2.000"),
        },
        org,
    )

    assert validated["product_obj"] == product
    assert validated["unit_obj"] == unit
    assert validated["tax_obj"] == tax
    assert validated["variant_obj"] == variant
    assert validated["addon_objs"] == [addon]


def test_create_order_item_rejects_foreign_addon(org_factory):
    org = org_factory()
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

    with pytest.raises(ValidationError, match="Invalid addons."):
        create_order_item(
            {
                "product": product.public_id,
                "unit": unit.public_id,
                "tax_rate": tax.public_id,
                "addons": [foreign_addon.public_id],
            },
            org,
        )
