from django.db import models
from django.db.models import Q, F

from config.orgs.models import OrgScopedModel


class StockLot(OrgScopedModel):
    label_code = models.CharField(max_length=64, blank=True, default="")
    batch_number = models.CharField(max_length=64, blank=True, default="")

    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="stock_lots",
    )
    supplier = models.ForeignKey(
        "partners.Partner",
        on_delete=models.PROTECT,
        related_name="stock_lots",
        null=True,
        blank=True,
    )

    initial_qty = models.DecimalField(max_digits=12, decimal_places=3)
    remaining_qty = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)

    received_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    storage_location = models.ForeignKey(
        "inventory.StorageLocation",
        on_delete=models.PROTECT,
        related_name="stock_lots",
        null=True,
        blank=True,
    )

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DEPLETED = "depleted", "Depleted"
        ARCHIVED = "archived", "Archived"

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    class Meta:
        ordering = ["received_at", "id"]
        indexes = [
            models.Index(fields=["org", "product", "status"]),
            models.Index(fields=["org", "expires_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(initial_qty__gt=0),
                name="stock_lot_initial_qty_gt_zero",
            ),
            models.CheckConstraint(
                condition=Q(remaining_qty__gte=0),
                name="stock_lot_remaining_qty_gte_zero",
            ),
            models.CheckConstraint(
                condition=Q(remaining_qty__lte=F("initial_qty")),
                name="stock_lot_remaining_qty_lte_initial_qty",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} - {self.label_code} ({self.remaining_qty}/{self.initial_qty})"


class StorageLocation(OrgScopedModel):
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    equipment = models.ForeignKey(
        "equipment.Equipment",
        on_delete=models.PROTECT,
        related_name="storage_locations",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "name"],
                name="uniq_storage_location_name_per_org",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class StockMovement(OrgScopedModel):
    class MovementType(models.TextChoices):
        IN = "in", "In"
        OUT = "out", "Out"
        WRITEOFF = "writeoff", "Write-off"
        ADJUSTMENT = "adjustment", "Adjustment"

    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    lot = models.ForeignKey(
        "inventory.StockLot",
        on_delete=models.PROTECT,
        related_name="movements",
    )
    movement_type = models.CharField(
        max_length=16,
        choices=MovementType.choices,
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=64, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["org", "product", "movement_type"]),
            models.Index(fields=["org", "lot", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="stock_movement_quantity_gt_zero",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product} {self.movement_type} {self.quantity}"
