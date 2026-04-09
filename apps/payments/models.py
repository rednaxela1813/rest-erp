from __future__ import annotations

from decimal import Decimal
import uuid

from django.conf import settings
from django.db import models

from config.orgs.models import OrgScopedModel


class Terminal(OrgScopedModel):
    STATUS_ACTIVE = "active"
    STATUS_INACTIVE = "inactive"

    STATUS_CHOICES = (
        (STATUS_ACTIVE, "Active"),
        (STATUS_INACTIVE, "Inactive"),
    )

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return self.name


class PaymentProviderConfig(OrgScopedModel):
    provider = models.CharField(max_length=64)
    name = models.CharField(max_length=255, blank=True, default="")
    credentials = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["id"]
        unique_together = ("org", "provider")

    def __str__(self) -> str:
        return f"{self.org_id}:{self.provider}"


class OrderPayment(OrgScopedModel):
    class Tender(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        ONLINE = "online", "Online"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        AUTHORIZED = "authorized", "Authorized"
        CAPTURED = "captured", "Captured"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"

    class CaptureStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        TIMEOUT = "timeout", "Timeout"
        CONFIRMED = "confirmed", "Confirmed"

    class FiscalStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        FAILED = "failed", "Failed"
        CONFIRMED = "confirmed", "Confirmed"

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="payments",
    )
    terminal = models.ForeignKey(
        "payments.Terminal",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )

    tender = models.CharField(max_length=16, choices=Tender.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3)

    provider = models.CharField(max_length=64, default="manual")
    provider_reference = models.CharField(max_length=128, blank=True, default="")
    raw_provider_payload = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=64, null=True, blank=True)

    authorized_at = models.DateTimeField(null=True, blank=True)
    captured_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(max_length=255, blank=True, default="")

    # Separate status trackers for outage-resilient capture and fiscalization.
    # Null keeps existing data neutral until workflows are wired in.
    capture_status = models.CharField(
        max_length=16,
        choices=CaptureStatus.choices,
        null=True,
        blank=True,
    )
    fiscal_status = models.CharField(
        max_length=16,
        choices=FiscalStatus.choices,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False),
                name="uniq_payment_idempotency_per_org",
            ),
        ]

    def __str__(self) -> str:
        return f"Payment {self.public_id}"


class PaymentEvent(models.Model):
    class Type(models.TextChoices):
        AUTHORIZED = "authorized", "Authorized"
        CAPTURED = "captured", "Captured"
        CANCELLED = "cancelled", "Cancelled"
        FAILED = "failed", "Failed"

    public_id = models.UUIDField(editable=False, unique=True, default=uuid.uuid4)

    org = models.ForeignKey(
        "orgs.Organization",
        on_delete=models.PROTECT,
        related_name="payment_events",
    )
    payment = models.ForeignKey(
        "payments.OrderPayment",
        on_delete=models.CASCADE,
        related_name="events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_events",
    )

    event_type = models.CharField(max_length=32, choices=Type.choices)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["org", "payment", "created_at"]),
        ]


class FiscalReceipt(models.Model):
    """
    Internal record of fiscal document issuance (sale/refund/storno/cash in/out).
    Stores device payload for audit and future adapter integration.
    """
    class Type(models.TextChoices):
        SALE = "sale", "Sale"
        REFUND = "refund", "Refund"
        STORNO = "storno", "Storno"
        CASH_IN = "cash_in", "Cash in"
        CASH_OUT = "cash_out", "Cash out"

    public_id = models.UUIDField(editable=False, unique=True, default=uuid.uuid4)
    org = models.ForeignKey(
        "orgs.Organization",
        on_delete=models.PROTECT,
        related_name="fiscal_receipts",
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="fiscal_receipts",
        null=True,
        blank=True,
    )
    payment = models.ForeignKey(
        "payments.OrderPayment",
        on_delete=models.PROTECT,
        related_name="fiscal_receipts",
        null=True,
        blank=True,
    )

    receipt_type = models.CharField(max_length=16, choices=Type.choices)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3)

    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Prevent duplicate receipts of the same type per payment.
            models.UniqueConstraint(
                fields=["payment", "receipt_type"],
                condition=models.Q(payment__isnull=False),
                name="uniq_fiscal_receipt_per_payment_type",
            ),
        ]


class DeviceCommand(models.Model):
    """
    Outbox command for Local Agent / device adapters.

    This model is intentionally generic:
    - The server only enqueues commands and tracks delivery status.
    - A separate Local Agent pulls commands and reports ACK/FAIL.
    - The server never talks to USB/COM directly.
    """

    class Type(models.TextChoices):
        FISCALIZE_SALE = "fiscalize_sale", "Fiscalize sale"
        FISCALIZE_REFUND = "fiscalize_refund", "Fiscalize refund"
        FISCALIZE_STORNO = "fiscalize_storno", "Fiscalize storno"
        PRINT_KOT = "print_kot", "Print kitchen order ticket"
        PRINT_RECEIPT = "print_receipt", "Print customer receipt"
        PAYMENT_CAPTURE = "payment_capture", "Capture payment"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        ACKED = "acked", "Acknowledged"
        FAILED = "failed", "Failed"

    public_id = models.UUIDField(editable=False, unique=True, default=uuid.uuid4)

    org = models.ForeignKey(
        "orgs.Organization",
        on_delete=models.PROTECT,
        related_name="device_commands",
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="device_commands",
        null=True,
        blank=True,
    )
    payment = models.ForeignKey(
        "payments.OrderPayment",
        on_delete=models.PROTECT,
        related_name="device_commands",
        null=True,
        blank=True,
    )

    command_type = models.CharField(max_length=32, choices=Type.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    # Payload is adapter-specific (e.g., fiscal SDK or printer driver).
    # We store it here for retries and audit.
    payload = models.JSONField(default=dict, blank=True)

    # Idempotency is required for safe retries and repeated requests.
    idempotency_key = models.CharField(max_length=128)

    retries = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=5)
    last_error = models.TextField(blank=True, default="")
    # When set, workers should not retry this command before the timestamp.
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "idempotency_key"],
                name="uniq_device_command_idempotency_per_org",
            ),
        ]


CASHIER_SESSION_STATUS_OPEN = "open"
CASHIER_SESSION_STATUS_CLOSED = "closed"

CASHIER_SESSION_STATUS_CHOICES = (
    (CASHIER_SESSION_STATUS_OPEN, "Open"),
    (CASHIER_SESSION_STATUS_CLOSED, "Closed"),
)


class CashierSession(OrgScopedModel):
    STATUS_OPEN = CASHIER_SESSION_STATUS_OPEN
    STATUS_CLOSED = CASHIER_SESSION_STATUS_CLOSED
    STATUS_CHOICES = CASHIER_SESSION_STATUS_CHOICES

    terminal = models.ForeignKey(
        "payments.Terminal",
        on_delete=models.PROTECT,
        related_name="sessions",
    )
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cashier_sessions",
    )

    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN,
    )

    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    cash_drawer_start = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    cash_drawer_end = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["org", "terminal"],
                condition=models.Q(status=CASHIER_SESSION_STATUS_OPEN),
                name="uniq_open_session_per_terminal_org",
            ),
        ]


class CashDrawerMovement(models.Model):
    class Type(models.TextChoices):
        OPENING_FLOAT = "opening_float", "Opening float"
        CASH_IN = "cash_in", "Cash in"
        CASH_OUT = "cash_out", "Cash out"
        SALE_CASH = "sale_cash", "Cash sale"

    public_id = models.UUIDField(editable=False, unique=True, default=uuid.uuid4)
    session = models.ForeignKey(
        "payments.CashierSession",
        on_delete=models.CASCADE,
        related_name="cash_movements",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_drawer_movements",
    )
    movement_type = models.CharField(max_length=32, choices=Type.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    reason = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["session", "created_at"]),
        ]
