# apps/accounting/logic/record_sale.py

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.accounting.models import AccountingEntry
from apps.orders.models import Order


_TENDER_TO_ENTRY_TYPE = {
    "cash": AccountingEntry.EntryType.SALE_CASH,
    "card": AccountingEntry.EntryType.SALE_CARD,
}


def record_sale(*, order: Order, tender: str) -> AccountingEntry:
    """
    Создаёт запись типа SALE_CASH или SALE_CARD когда заказ оплачен.

    Звёздочка в аргументах (*) означает что все аргументы
    передаются только по имени: record_sale(order=order)
    Это защита от случайной передачи в неправильном порядке.
    """

    # ContentType.objects.get_for_model() возвращает запись
    # из таблицы django_content_type для модели Order.
    # Django кеширует это — повторные вызовы не идут в базу.
    ct = ContentType.objects.get_for_model(Order)

    # get_or_create возвращает (объект, создан_ли_он)
    # Если запись уже есть — вернёт её, не создаст дубль.
    entry_type = _TENDER_TO_ENTRY_TYPE.get(tender)
    if entry_type is None:
        raise ValueError(f"record_sale: неизвестный tender={tender!r}")
    # Это делает функцию идемпотентной.
    entry, created = AccountingEntry.objects.get_or_create(
        # По этим полям ищем существующую запись:
        org=order.org,
        source_content_type=ct,
        source_object_id=order.pk,
        entry_type=entry_type,
        # Если не нашли — создаём с этими значениями:
        defaults={
            "amount": order.total,
            "tax_amount": order.tax_total,
            "currency": "EUR",
            "transaction_date": timezone.localdate(),
            "note": f"Order {order.public_id}",
        },
    )

    return entry
