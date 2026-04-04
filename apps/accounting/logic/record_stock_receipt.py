# apps/accounting/logic/record_stock_receipt.py

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.accounting.models import AccountingEntry
from apps.inventory.models import StockLot


def record_stock_receipt(*, lot: StockLot) -> AccountingEntry:
    """
    Создаёт запись типа STOCK_RECEIPT когда пришла партия товара.

    cost_amount = сколько мы заплатили за всю партию
    например: 10 булочек по 0.50 EUR = 5.00 EUR
    """

    ct = ContentType.objects.get_for_model(StockLot)

    # Считаем полную стоимость партии
    cost = (lot.initial_qty * lot.unit_cost).quantize(Decimal("0.01"))

    entry, created = AccountingEntry.objects.get_or_create(
        # По этим полям ищем — защита от дублей
        org=lot.org,
        source_content_type=ct,
        source_object_id=lot.pk,
        entry_type=AccountingEntry.EntryType.STOCK_RECEIPT,
        # Если не нашли — создаём с этими значениями
        defaults={
            "amount": cost,
            "tax_amount": Decimal("0.00"),  # НДС на закупку считается отдельно
            "currency": "EUR",
            "partner": lot.supplier,        # поставщик
            "transaction_date": lot.received_at.date() if lot.received_at else timezone.localdate(),
            "note": f"Приход: {lot.product.name} x {lot.initial_qty} по {lot.unit_cost}",
        },
    )

    return entry