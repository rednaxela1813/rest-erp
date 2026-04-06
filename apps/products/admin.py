from decimal import Decimal

from django.contrib import admin
from django import forms

from .models import BundleItem, Product, TaxRate, Unit


class BundleItemInline(admin.TabularInline):
    model = BundleItem
    extra = 1
    autocomplete_fields = ("component",)
    fk_name = "bundle"


class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        org_id = self._resolve_org_id()

        if "unit" in self.fields:
            unit_qs = Unit.objects.all()
            self.fields["unit"].queryset = (
                unit_qs.filter(org_id=org_id) if org_id else unit_qs.none()
            )
        if "tax_rate" in self.fields:
            tax_qs = TaxRate.objects.all()
            self.fields["tax_rate"].queryset = (
                tax_qs.filter(org_id=org_id) if org_id else tax_qs.none()
            )

    def _resolve_org_id(self):
        if self.is_bound:
            org_value = self.data.get("org")
            if org_value:
                return org_value

        if self.instance and self.instance.pk:
            return self.instance.org_id

        initial_org = self.initial.get("org")
        if hasattr(initial_org, "pk"):
            return initial_org.pk
        return initial_org


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
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
       
    )
    search_fields = ("name", "barcode", "org__name")
    list_filter = ("status", "tax_rate", "is_bundle", "requires_preparation")
    inlines = [BundleItemInline]

    

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
