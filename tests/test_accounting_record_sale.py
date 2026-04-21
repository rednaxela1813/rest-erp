# tests/test_accounting_record_sale.py

from decimal import Decimal
import pytest

from apps.accounting.logic.record_sale import record_sale
from apps.accounting.models import AccountingEntry
from apps.orders.models import Order, OrderItem
from apps.products.models import Product, TaxRate, Unit

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(*, org, name="Бургер") -> Product:
    unit = Unit.objects.create(org=org, name=f"{name}-unit")
    tax_rate = TaxRate.objects.create(org=org, name=f"{name}-tax", rate=Decimal("20.00"))
    return Product.objects.create(
        org=org,
        name=name,
        unit=unit,
        tax_rate=tax_rate,
        unit_price=Decimal("10.00"),
    )


def _make_paid_order(*, org) -> Order:
    product = _make_product(org=org)

    order = Order.objects.create(org=org, status=Order.STATUS_PAID)
    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("2.000"),
        unit=product.unit,
        unit_price=Decimal("10.00"),
        tax_rate=product.tax_rate,
    )
    order.recompute_totals()
    order.save()
    return order


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_record_sale_creates_entry(org_factory):
    org = org_factory()
    order = _make_paid_order(org=org)

    entry = record_sale(order=order, tender="cash")

    assert entry.pk is not None
    assert entry.entry_type == AccountingEntry.EntryType.SALE_CASH
    assert entry.amount == order.total
    assert entry.tax_amount == order.tax_total
    assert entry.org == org


def test_record_sale_export_status_is_pending(org_factory):
    # Каждая новая запись должна ждать экспорта в Money S3
    org = org_factory()
    order = _make_paid_order(org=org)

    entry = record_sale(order=order, tender="cash")

    assert entry.export_status == AccountingEntry.ExportStatus.PENDING
    assert entry.exported_at is None


def test_record_sale_is_idempotent(org_factory):
    # Если вызвать record_sale дважды для одного заказа —
    # должна быть только одна запись, не две
    org = org_factory()
    order = _make_paid_order(org=org)

    entry1 = record_sale(order=order, tender="cash")
    entry2 = record_sale(order=order, tender="cash")

    assert entry1.pk == entry2.pk
    assert AccountingEntry.objects.filter(org=org).count() == 1


def test_record_sale_links_to_order(org_factory):
    # Запись должна знать из какого заказа она родилась
    from django.contrib.contenttypes.models import ContentType

    org = org_factory()
    order = _make_paid_order(org=org)

    entry = record_sale(order=order, tender="cash")

    ct = ContentType.objects.get_for_model(Order)
    assert entry.source_content_type == ct
    assert entry.source_object_id == order.pk


def test_record_sale_org_isolation(org_factory):
    # Записи одной организации не видны другой
    org_a = org_factory(name="Org A")
    org_b = org_factory(name="Org B")

    order_a = _make_paid_order(org=org_a)
    order_b = _make_paid_order(org=org_b)

    record_sale(order=order_a, tender="cash")
    record_sale(order=order_b, tender="cash")

    assert AccountingEntry.objects.filter(org=org_a).count() == 1
    assert AccountingEntry.objects.filter(org=org_b).count() == 1
