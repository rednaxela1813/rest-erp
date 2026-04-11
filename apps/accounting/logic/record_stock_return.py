# apps/accounting/logic/record_stock_return.py

from django.contrib.contenttypes.models import ContentType
from decimal import Decimal

from apps.accounting.models import AccountingEntry
from apps.inventory.models import StockMovement


def record_stock_return(*, movement: StockMovement) -> AccountingEntry:
    """
    Создаёт запись типа STOCK_RECEIPT когда товар возвращён на склад
    при отмене/возврате заказа.

    amount — себестоимость возвращённого товара (положительная,
    т.к. это приход на склад).
    Идемпотентна: повторный вызов вернёт существующую запись.
    """
    ct = ContentType.objects.get_for_model(StockMovement)

    cost = (movement.quantity * movement.unit_cost_snapshot).quantize(
        Decimal("0.01")
    )

    entry, _ = AccountingEntry.objects.get_or_create(
        org=movement.org,
        source_content_type=ct,
        source_object_id=movement.pk,
        entry_type=AccountingEntry.EntryType.STOCK_RECEIPT,
        defaults={
            "amount": cost,
            "tax_amount": Decimal("0.00"),
            "currency": "EUR",
            "transaction_date": movement.created_at.date(),
            "note": (
                f"Возврат: {movement.product.name} "
                f"x {movement.quantity} "
                f"по {movement.unit_cost_snapshot} "
                f"из партии {movement.lot.label_code or movement.lot.pk}"
            ),
        },
    )

    return entry
