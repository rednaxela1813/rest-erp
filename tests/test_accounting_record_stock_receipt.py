# tests/test_accounting_record_stock_receipt.py

from decimal import Decimal
import pytest

from apps.accounting.models import AccountingEntry
from apps.inventory.services.receive_stock import receive_stock
from apps.products.models import Product, TaxRate, Unit

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_product(*, org, name="Булочки") -> Product:
    unit = Unit.objects.create(org=org, name=f"{name}-unit")
    tax_rate = TaxRate.objects.create(org=org, name=f"{name}-tax", rate=Decimal("20.00"))
    return Product.objects.create(
        org=org,
        name=name,
        unit=unit,
        tax_rate=tax_rate,
        unit_price=Decimal("0.50"),
    )


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

def test_receive_stock_creates_accounting_entry(org_factory):
    # При приходе товара должна создаться бухгалтерская запись
    org = org_factory()
    product = _make_product(org=org)

    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("100.000"),
        unit_cost=Decimal("0.30"),
    )

    entry = AccountingEntry.objects.get(
        org=org,
        entry_type=AccountingEntry.EntryType.STOCK_RECEIPT,
    )
    assert entry.amount == Decimal("30.00")  # 100 × 0.30


def test_receive_stock_entry_links_to_lot(org_factory):
    # Запись должна ссылаться на созданную партию
    from django.contrib.contenttypes.models import ContentType
    from apps.inventory.models import StockLot

    org = org_factory()
    product = _make_product(org=org)

    lot, _ = receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.00"),
    )

    entry = AccountingEntry.objects.get(
        org=org,
        entry_type=AccountingEntry.EntryType.STOCK_RECEIPT,
    )
    ct = ContentType.objects.get_for_model(StockLot)

    assert entry.source_content_type == ct
    assert entry.source_object_id == lot.pk


def test_receive_stock_entry_links_supplier(org_factory):
    # Если указан поставщик — он должен попасть в запись
    from apps.partners.models import Partner

    org = org_factory()
    product = _make_product(org=org)
    supplier = Partner.objects.create(org=org, name="Хлебзавод №1")

    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("50.000"),
        unit_cost=Decimal("0.50"),
        supplier=supplier,
    )

    entry = AccountingEntry.objects.get(
        org=org,
        entry_type=AccountingEntry.EntryType.STOCK_RECEIPT,
    )
    assert entry.partner == supplier


def test_receive_stock_rolls_back_if_accounting_fails(org_factory, monkeypatch):
    from apps.inventory.models import StockLot, StockMovement
    import apps.inventory.services.receive_stock as module  # ← патчим здесь

    org = org_factory()
    product = _make_product(org=org)

    def broken_record(*args, **kwargs):
        raise Exception("бухгалтерия сломалась")

    monkeypatch.setattr(module, "record_stock_receipt", broken_record)  # ← здесь

    with pytest.raises(Exception, match="бухгалтерия сломалась"):
        receive_stock(
            org=org,
            product=product,
            initial_qty=Decimal("10.000"),
            unit_cost=Decimal("1.00"),
        )

    assert StockLot.objects.filter(org=org).count() == 0
    assert StockMovement.objects.filter(org=org).count() == 0
    assert AccountingEntry.objects.filter(org=org).count() == 0