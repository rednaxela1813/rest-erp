from __future__ import annotations

from rest_framework.exceptions import ValidationError

from apps.orders.models import OrderItem, OrderItemAddon
from apps.products.models import Product, ProductAddon, ProductVariant, TaxRate, Unit


def create_order_item(data: dict, org) -> dict:
    validated = dict(data)

    try:
        product_obj = Product.objects.get(
            org=org,
            public_id=validated["product"],
            status=Product.STATUS_ACTIVE,
        )
    except Product.DoesNotExist as exc:
        raise ValidationError({"product": "Invalid product."}) from exc

    try:
        unit_obj = Unit.objects.get(
            org=org,
            public_id=validated["unit"],
            status=Unit.STATUS_ACTIVE,
        )
    except Unit.DoesNotExist as exc:
        raise ValidationError({"unit": "Invalid unit."}) from exc

    try:
        tax_obj = TaxRate.objects.get(
            org=org,
            public_id=validated["tax_rate"],
            status=TaxRate.STATUS_ACTIVE,
        )
    except TaxRate.DoesNotExist as exc:
        raise ValidationError({"tax_rate": "Invalid tax_rate."}) from exc

    validated["product_obj"] = product_obj
    validated["unit_obj"] = unit_obj
    validated["tax_obj"] = tax_obj

    variant_public_id = validated.get("variant")
    if variant_public_id:
        try:
            variant_obj = product_obj.variants.get(
                public_id=variant_public_id,
                status=ProductVariant.STATUS_ACTIVE,
            )
        except ProductVariant.DoesNotExist as exc:
            raise ValidationError({"variant": "Invalid variant."}) from exc
        validated["variant_obj"] = variant_obj

    addon_public_ids = validated.get("addons") or []
    addon_objs = list(
        ProductAddon.objects.filter(
            product=product_obj,
            public_id__in=addon_public_ids,
            status=ProductAddon.STATUS_ACTIVE,
        )
    )
    if len(addon_objs) != len(addon_public_ids):
        raise ValidationError({"addons": "Invalid addons."})

    validated["addon_objs"] = addon_objs
    return validated


def create_order_item_record(validated_data: dict) -> OrderItem:
    data = dict(validated_data)
    product_obj = data.pop("product_obj")
    unit_obj = data.pop("unit_obj")
    tax_obj = data.pop("tax_obj")
    variant_obj = data.pop("variant_obj", None)
    addon_objs = data.pop("addon_objs", [])

    data.pop("product", None)
    data.pop("unit", None)
    data.pop("tax_rate", None)
    data.pop("variant", None)
    data.pop("addons", None)

    data["product_name"] = product_obj.name
    data["variant_name"] = variant_obj.name if variant_obj else ""

    item = OrderItem.objects.create(
        product=product_obj,
        unit=unit_obj,
        tax_rate=tax_obj,
        variant=variant_obj,
        **data,
    )

    if addon_objs:
        OrderItemAddon.objects.bulk_create(
            [
                OrderItemAddon(
                    order_item=item,
                    addon=addon,
                    name=addon.name,
                    price=addon.price,
                    qty=item.qty,
                )
                for addon in addon_objs
            ]
        )

    return item
