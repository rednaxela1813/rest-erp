# apps/accounting/models.py

from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from config.orgs.models import OrgScopedModel


class AccountingEntry(OrgScopedModel):

    class EntryType(models.TextChoices):
        SALE          = "sale",          "Продажа"
        REFUND        = "refund",        "Возврат"
        REFUND_CASH   = "refund_cash",   "Возврат наличными"
        REFUND_CARD   = "refund_card",   "Возврат по карте"
        STOCK_RECEIPT = "stock_receipt", "Приход товара"
        STOCK_OUT     = "stock_out",     "Расход товара"
        PAYMENT_OUT   = "payment_out",   "Оплата поставщику"
        SALE_CASH     = "sale_cash",    "Продажа наличными"
        SALE_CARD     = "sale_card",    "Продажа картой"
        CASH_IN       = "cash_in",      "Внесение наличных"
        CASH_OUT      = "cash_out",     "Изъятие наличных"
        
    class ExportStatus(models.TextChoices):
        PENDING  = "pending",  "Ожидает экспорта"
        EXPORTED = "exported", "Экспортировано"
        FAILED   = "failed",   "Ошибка экспорта"
  
    entry_type = models.CharField(max_length=32, choices=EntryType.choices)

    amount     = models.DecimalField(max_digits=12, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency   = models.CharField(max_length=3, default="EUR")
    partner = models.ForeignKey("partners.Partner", on_delete=models.PROTECT, null=True, blank=True, related_name="accounting_entries"    )
    note = models.TextField(blank=True, default="")
    transaction_date = models.DateField()

    # --- Связь с источником события ---
    # Вместе эти три поля отвечают на вопрос "из какого объекта родилась эта запись"
    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.PROTECT,   # нельзя удалить тип если есть записи
        null=True,
        blank=True,
        related_name="+",           # "+" = не создавать обратную связь
    )
    source_object_id = models.PositiveIntegerField(null=True, blank=True)
    source_object    = GenericForeignKey("source_content_type", "source_object_id")
    
    export_status = models.CharField(max_length=16, choices=ExportStatus.choices, default=ExportStatus.PENDING, db_index=True, )
    exported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-transaction_date", "-created_at"]

    def __str__(self):
        return f"{self.entry_type} {self.amount} {self.currency} [{self.transaction_date}] ({self.export_status})"