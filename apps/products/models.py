#apps/products/models.py
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from config.orgs.models import OrgScopedModel
from decimal import Decimal


class Unit(OrgScopedModel):
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_ARCHIVED, "Archived"),
    )

    name = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)

    class Meta:
        ordering = ["id"]
        constraints = [
    models.UniqueConstraint(
        fields=["org", "name"],
        condition=models.Q(status="active"),
        name="uniq_active_unit_name_per_org",
    ),
]


    def __str__(self) -> str:
        return self.name




class TaxRate(OrgScopedModel):
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_ARCHIVED, "Archived"),
    )

    name = models.CharField(max_length=64)
    rate = models.DecimalField(max_digits=5, decimal_places=2)  # 20.00, 10.00, 0.00
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "name"],
                condition=models.Q(status="active"),
                name="uniq_active_taxrate_name_per_org",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.rate}%)"


class Product(OrgScopedModel):
    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_ARCHIVED, "Archived"),
    )

    name = models.CharField(max_length=255)
    barcode = models.CharField(max_length=64, blank=True, default="", db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    is_bundle = models.BooleanField(default=False)
    requires_preparation = models.BooleanField(default=False)
    bundle_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
    )
    
    unit = models.ForeignKey(
        "products.Unit",
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
    )
    tax_rate = models.ForeignKey(
        "products.TaxRate",
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    stock_qty = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
    )
    
    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "name"],
                condition=models.Q(status="active"),
                name="uniq_active_product_name_per_org",
            ),
            models.UniqueConstraint(
                fields=["org", "barcode"],
                condition=models.Q(barcode__gt=""),
                name="uniq_product_barcode_per_org",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def recompute_bundle_price(self) -> Decimal:
        if not self.is_bundle:
            return self.unit_price
        total = Decimal("0.00")
        for item in self.bundle_items.select_related("component").all():
            if not item.component:
                continue
            total += (item.component.unit_price * item.qty)
        discount = total * (self.bundle_discount_percent / Decimal("100"))
        price = (total - discount).quantize(Decimal("0.01"))
        return price


class BundleItem(models.Model):
    bundle = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="bundle_items")
    component = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="bundle_components")
    qty = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("1.000"))

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["bundle", "component"], name="uniq_bundle_component"),
        ]
        ordering = ["id"]

    def clean(self) -> None:
        super().clean()
        if self.bundle_id and self.component_id and self.bundle_id == self.component_id:
            raise ValidationError("Bundle component cannot be the bundle itself.")
        if self.bundle and self.component and self.bundle.org_id != self.component.org_id:
            raise ValidationError("Bundle components must belong to the same organization.")
        if self.bundle and not self.bundle.is_bundle:
            raise ValidationError("Bundle items can only be added to bundle products.")

    def __str__(self) -> str:
        return f"{self.bundle.name}: {self.component.name} x {self.qty}"
