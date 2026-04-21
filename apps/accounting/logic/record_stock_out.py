# apps/accounting/logic/record_stock_out.py

from django.contrib.contenttypes.models import ContentType

from apps.accounting.models import AccountingEntry
from apps.inventory.models import StockMovement
from decimal import Decimal


def record_stock_out(*, movement: StockMovement) -> AccountingEntry:
    """
    Создаёт запись типа STOCK_OUT когда товар списан со склада при продаже.

    amount = количество × себестоимость из партии
    Это себестоимость без НДС — нужна для расчёта food cost.
    """

    ct = ContentType.objects.get_for_model(StockMovement)

    # Себестоимость списанного = сколько единиц × цена за единицу в этой партии
    cost = (movement.quantity * movement.unit_cost_snapshot).quantize(movement.unit_cost_snapshot.__class__("0.01"))

    entry, created = AccountingEntry.objects.get_or_create(
        # По этим полям ищем — защита от дублей
        org=movement.org,
        source_content_type=ct,
        source_object_id=movement.pk,
        entry_type=AccountingEntry.EntryType.STOCK_OUT,
        defaults={
            "amount": cost,
            "tax_amount": Decimal("0.00"),  # НДС не нужен, т.к. это внутренний расход
            "currency": "EUR",
            "transaction_date": movement.created_at.date(),
            "note": (
                f"Списание: {movement.product.name} "
                f"x {movement.quantity} "
                f"по {movement.unit_cost_snapshot} "
                f"из партии {movement.lot.label_code or movement.lot.pk}"
            ),
        },
    )

    return entry
