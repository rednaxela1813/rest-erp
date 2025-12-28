#apps/products/models.py
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
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    
    stock_qty = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0.000"))
    
    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "name"],
                condition=models.Q(status="active"),
                name="uniq_active_product_name_per_org",
            ),
        ]

    def __str__(self) -> str:
        return self.name
