# apps/payments/models.py
from decimal import Decimal

from django.conf import settings
from django.db import models
from .models_terminal import Terminal  # noqa: F401

from django.core.exceptions import ValidationError

from config.orgs.models import OrgScopedModel


class OrderPayment(OrgScopedModel):
    """
    Платёж/транзакция по заказу.

    Важные поля MVP:
    - org-scope обязателен: все уникальности (idempotency_key / external_id) работают ВНУТРИ org.
    - status в MVP пока меняем только через use-case (ниже).
      (Модельный запрет на прямую смену статуса добавим отдельным шагом с тестом.)
    """

    class Tender(models.TextChoices):
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        PREPAID_EXTERNAL = "prepaid_external", "Prepaid external"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        AUTHORIZED = "authorized", "Authorized"
        CAPTURED = "captured", "Captured"
        REFUNDED = "refunded", "Refunded"
        VOIDED = "voided", "Voided"
        FAILED = "failed", "Failed"

    
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="payments")

    

    tender = models.CharField(max_length=32, choices=Tender.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)

    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=8, default="EUR")

    # Идемпотентность/интеграции
    idempotency_key = models.CharField(max_length=128, null=True, blank=True)
    external_id = models.CharField(max_length=128, null=True, blank=True)
    provider = models.CharField(max_length=64, default="manual")

    raw_provider_payload = models.JSONField(null=True, blank=True)

    
    
    # флаг (по умолчанию False) — use-case временно выставляет True
    _status_change_allowed: bool = False
    _loaded_status: str | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # В момент создания объекта в памяти фиксируем статус как "загруженный"
        self._loaded_status = self.status

    @classmethod
    def from_db(cls, db, field_names, values):
        """
        Django вызывает from_db при загрузке из БД.
        Здесь фиксируем статус, чтобы отлавливать изменения позже.
        """
        instance = super().from_db(db, field_names, values)
        instance._loaded_status = instance.status
        instance._status_change_allowed = False
        return instance
    
    def save(self, *args, **kwargs):
        """
        Инвариант: статус нельзя менять прямым .save().
        Менять статус можно только через use-case, который выставляет
        payment._status_change_allowed = True перед сохранением.

        Это защита от "тихих" обновлений в коде/админке, которые обходят аудит.
        """
        if self.pk is not None:
            status_changed = (self._loaded_status is not None) and (self.status != self._loaded_status)
            if status_changed and not getattr(self, "_status_change_allowed", False):
                raise ValidationError("OrderPayment.status can only be changed via use-case")

        super().save(*args, **kwargs)

        # После успешного сохранения обновляем "загруженный" статус
        self._loaded_status = self.status
        self._status_change_allowed = False


    class Meta:
        constraints = [
            # UNIQUE внутри org, но nullable допускает много NULL (в Postgres это ок)
            models.UniqueConstraint(fields=["org", "idempotency_key"], name="uniq_payment_org_idempotency"),
            models.UniqueConstraint(fields=["org", "external_id"], name="uniq_payment_org_external_id"),
        ]

    def __str__(self) -> str:
        return f"Payment({self.public_id}) {self.status} {self.amount} {self.currency}"


class PaymentEvent(OrgScopedModel):
    """
    Аудит жизненного цикла платежа.
    В MVP фиксируем:
    - создание платежа (from_status=None -> to_status=pending, action='create')
    """

    
    payment = models.ForeignKey("payments.OrderPayment", on_delete=models.CASCADE, related_name="events")

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    # В следующих MVP-шагах сюда добавим terminal/session/external_source
    terminal = models.ForeignKey("payments.Terminal", null=True, blank=True, on_delete=models.SET_NULL)

    from_status = models.CharField(max_length=32, null=True, blank=True)
    to_status = models.CharField(max_length=32)
    action = models.CharField(max_length=32)  # create / authorize / capture / refund / void / webhook / ...

    metadata = models.JSONField(default=dict, blank=True)

    

    def __str__(self) -> str:
        return f"PaymentEvent({self.payment_id}) {self.action} {self.from_status}->{self.to_status}"
