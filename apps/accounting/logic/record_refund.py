# apps/accounting/logic/record_refund.py

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.accounting.models import AccountingEntry
from apps.orders.models import Order


_TENDER_TO_REFUND_TYPE = {
    "cash": AccountingEntry.EntryType.REFUND_CASH,
    "card": AccountingEntry.EntryType.REFUND_CARD,
}


def record_refund(*, order: Order, tender: str) -> AccountingEntry:
    """
    Создаёт запись REFUND_CASH или REFUND_CARD когда оплаченный заказ возвращён.

    Сумма — отрицательная (деньги уходят из кассы обратно покупателю).
    Идемпотентна: повторный вызов вернёт существующую запись.
    """
    ct = ContentType.objects.get_for_model(Order)

    entry_type = _TENDER_TO_REFUND_TYPE.get(tender)
    if entry_type is None:
        raise ValueError(f"record_refund: неизвестный tender={tender!r}")

    entry, _ = AccountingEntry.objects.get_or_create(
        org=order.org,
        source_content_type=ct,
        source_object_id=order.pk,
        entry_type=entry_type,
        defaults={
            "amount": -order.total,
            "tax_amount": -order.tax_total,
            "currency": "EUR",
            "transaction_date": timezone.localdate(),
            "note": f"Refund: Order {order.public_id} ({tender})",
        },
    )

    return entry
