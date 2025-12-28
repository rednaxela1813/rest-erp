
# apps/orders/models.py
from __future__ import annotations
from django.db import models
from decimal import Decimal
import uuid

from config.orgs.models import OrgScopedModel
from apps.products.models import Unit, TaxRate
from django.db.models import F, Sum, DecimalField, ExpressionWrapper


from django.conf import settings


from config.orgs.models import Organization  # если у тебя так называется модель org


class Order(OrgScopedModel):
    STATUS_DRAFT = "draft"
    STATUS_PAID = "paid"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_PAID, "Paid"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )
    
    
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    
    def recompute_totals(self) -> None:
        """
        Minimal: totals = sum(qty * unit_price), tax_total = subtotal * (rate/100) per item, total = subtotal + tax_total
        """
        items = self.items.select_related("tax_rate").all()

        subtotal = Decimal("0.00")
        tax_total = Decimal("0.00")

        for it in items:
            line_base = (it.qty * it.unit_price)
            subtotal += line_base
            tax_total += (line_base * it.tax_rate.rate / Decimal("100"))

        # normalize to 2 decimals
        self.subtotal = subtotal.quantize(Decimal("0.01"))
        self.tax_total = tax_total.quantize(Decimal("0.01"))
        self.total = (self.subtotal + self.tax_total).quantize(Decimal("0.01"))
        
        
    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"Order {self.public_id}"



class OrderItem(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="items",
    )
    
    product = models.ForeignKey("products.Product", on_delete=models.PROTECT, related_name="order_items", null=True, blank=True)

    product_name = models.CharField(max_length=255)
    qty = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("1.000"))

    unit = models.ForeignKey(
        "products.Unit",
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    tax_rate = models.ForeignKey(
        "products.TaxRate",
        on_delete=models.PROTECT,
        related_name="order_items",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.product_name} x {self.qty}"
    
    





class OrderStatusEvent(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    org = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="order_status_events")
    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="status_events")

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_status_events",
    )

    from_status = models.CharField(max_length=32)
    to_status = models.CharField(max_length=32)

    reason = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(blank=True, default=dict)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["org", "order", "created_at"]),
            models.Index(fields=["order", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.order_id}: {self.from_status} -> {self.to_status}"

