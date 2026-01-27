from decimal import Decimal

from django.contrib import admin

from .models import BundleItem, Product, TaxRate, Unit


class BundleItemInline(admin.TabularInline):
    model = BundleItem
    extra = 1
    autocomplete_fields = ("component",)
    fk_name = "bundle"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "org",
        "status",
        "barcode",
        "is_bundle",
        "requires_preparation",
        "bundle_discount_percent",
        "unit_price",
        "unit",
        "tax_rate",
        "stock_qty",
    )
    search_fields = ("name", "barcode", "org__name")
    list_filter = ("status", "tax_rate", "is_bundle", "requires_preparation")
    inlines = [BundleItemInline]

    def save_model(self, request, obj, form, change):
        if obj.requires_preparation:
            obj.stock_qty = None
        elif obj.stock_qty is None:
            obj.stock_qty = Decimal("0.000")
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        product = form.instance
        if product.is_bundle:
            new_price = product.recompute_bundle_price()
            if product.unit_price != new_price:
                product.unit_price = new_price
                fields = ["unit_price"]
                if "updated_at" in [f.name for f in product._meta.fields]:
                    fields.append("updated_at")
                product.save(update_fields=fields)


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "org", "status")
    search_fields = ("name", "org__name")
    list_filter = ("status",)


@admin.register(TaxRate)
class TaxRateAdmin(admin.ModelAdmin):
    list_display = ("name", "rate", "org", "status")
    search_fields = ("name", "org__name")
    list_filter = ("status",)
