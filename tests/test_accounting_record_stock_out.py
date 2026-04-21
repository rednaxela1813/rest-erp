# tests/test_accounting_record_stock_out.py

from decimal import Decimal
import pytest

from apps.accounting.models import AccountingEntry
from apps.inventory.services.receive_stock import receive_stock
from apps.inventory.services.deduct_stock import deduct_stock
from apps.products.models import Product, TaxRate, Unit

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(*, org, name="Котлета") -> Product:
    unit = Unit.objects.create(org=org, name=f"{name}-unit")
    tax_rate = TaxRate.objects.create(org=org, name=f"{name}-tax", rate=Decimal("20.00"))
    return Product.objects.create(
        org=org,
        name=name,
        unit=unit,
        tax_rate=tax_rate,
        unit_price=Decimal("3.00"),
    )


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


def test_deduct_stock_creates_stock_out_entry(org_factory):
    # При списании товара должна создаться запись STOCK_OUT
    org = org_factory()
    product = _make_product(org=org)

    # Сначала оприходуем товар
    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.50"),
    )

    # Списываем
    deduct_stock(
        org=org,
        product=product,
        quantity=Decimal("2.000"),
        reason="order_paid",
    )

    entry = AccountingEntry.objects.get(
        org=org,
        entry_type=AccountingEntry.EntryType.STOCK_OUT,
    )

    # 2 × 1.50 = 3.00
    assert entry.amount == Decimal("3.00")


def test_stock_out_entry_amount_is_cost_not_price(org_factory):
    # amount должен быть себестоимостью (закупочная цена),
    # а не розничной ценой продукта
    org = org_factory()
    product = _make_product(org=org)

    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.50"),  # закупочная цена
    )

    deduct_stock(
        org=org,
        product=product,
        quantity=Decimal("1.000"),
        reason="order_paid",
    )

    entry = AccountingEntry.objects.get(
        org=org,
        entry_type=AccountingEntry.EntryType.STOCK_OUT,
    )

    # должна быть закупочная цена 1.50, не розничная 3.00
    assert entry.amount == Decimal("1.50")
    assert entry.amount != product.unit_price


def test_stock_out_links_to_movement(org_factory):
    # Запись должна ссылаться на StockMovement
    from django.contrib.contenttypes.models import ContentType
    from apps.inventory.models import StockMovement

    org = org_factory()
    product = _make_product(org=org)

    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.50"),
    )

    movements = deduct_stock(
        org=org,
        product=product,
        quantity=Decimal("2.000"),
        reason="order_paid",
    )

    entry = AccountingEntry.objects.get(
        org=org,
        entry_type=AccountingEntry.EntryType.STOCK_OUT,
    )

    ct = ContentType.objects.get_for_model(StockMovement)
    assert entry.source_content_type == ct
    assert entry.source_object_id == movements[0].pk


def test_stock_out_is_idempotent(org_factory):
    # Повторный вызов record_stock_out для того же движения
    # не должен создавать дубли
    from apps.accounting.logic.record_stock_out import record_stock_out

    org = org_factory()
    product = _make_product(org=org)

    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.50"),
    )

    movements = deduct_stock(
        org=org,
        product=product,
        quantity=Decimal("2.000"),
        reason="order_paid",
    )

    # Вызываем дважды для одного движения
    record_stock_out(movement=movements[0])
    record_stock_out(movement=movements[0])

    assert (
        AccountingEntry.objects.filter(
            org=org,
            entry_type=AccountingEntry.EntryType.STOCK_OUT,
        ).count()
        == 1
    )
