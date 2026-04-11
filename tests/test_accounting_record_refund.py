# tests/test_accounting_record_refund.py

from decimal import Decimal
import pytest

from apps.accounting.models import AccountingEntry
from apps.orders.models import Order, OrderItem
from apps.payments.models import OrderPayment
from apps.products.models import Product, TaxRate, Unit

pytestmark = pytest.mark.django_db


def _make_product(*, org, name="Cola", requires_preparation=False):
    unit = Unit.objects.create(org=org, name=f"{name}-unit")
    tax_rate = TaxRate.objects.create(org=org, name=f"{name}-tax", rate=Decimal("23.00"))
    return Product.objects.create(
        org=org,
        name=name,
        unit=unit,
        tax_rate=tax_rate,
        unit_price=Decimal("2.00"),
        requires_preparation=requires_preparation,
    )


def _make_paid_order_with_payment(*, org, product, tender="cash", lot=None):
    order = Order.objects.create(org=org, status=Order.STATUS_PAID)
    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("1.000"),
        unit=product.unit,
        unit_price=Decimal("2.00"),
        tax_rate=product.tax_rate,
    )
    order.recompute_totals()
    order.save()

    OrderPayment.objects.create(
        org=org,
        order=order,
        tender=tender,
        status=OrderPayment.Status.CAPTURED,
        amount=order.total,
        currency="EUR",
        provider="manual",
    )

    if lot is not None:
        from apps.inventory.services.deduct_stock import deduct_stock
        deduct_stock(org=org, product=product, quantity=Decimal("1.000"), reason="order_paid")

    return order


# ---------------------------------------------------------------------------
# Tests: record_refund
# ---------------------------------------------------------------------------

def test_record_refund_cash_creates_refund_cash_entry(org_factory):
    """Возврат наличными → запись REFUND_CASH."""
    from apps.accounting.logic.record_refund import record_refund

    org = org_factory()
    product = _make_product(org=org)
    order = _make_paid_order_with_payment(org=org, product=product, tender="cash")

    entry = record_refund(order=order, tender="cash")

    assert entry.entry_type == AccountingEntry.EntryType.REFUND_CASH
    assert entry.amount == -order.total
    assert entry.tax_amount == -order.tax_total
    assert entry.export_status == AccountingEntry.ExportStatus.PENDING


def test_record_refund_card_creates_refund_card_entry(org_factory):
    """Возврат по карте → запись REFUND_CARD."""
    from apps.accounting.logic.record_refund import record_refund

    org = org_factory()
    product = _make_product(org=org)
    order = _make_paid_order_with_payment(org=org, product=product, tender="card")

    entry = record_refund(order=order, tender="card")

    assert entry.entry_type == AccountingEntry.EntryType.REFUND_CARD
    assert entry.amount == -order.total


def test_record_refund_unknown_tender_raises(org_factory):
    """Неизвестный tender → ValueError."""
    from apps.accounting.logic.record_refund import record_refund

    org = org_factory()
    product = _make_product(org=org)
    order = _make_paid_order_with_payment(org=org, product=product)

    with pytest.raises(ValueError, match="tender"):
        record_refund(order=order, tender="bitcoin")


def test_record_refund_is_idempotent(org_factory):
    """Повторный вызов не создаёт дубль."""
    from apps.accounting.logic.record_refund import record_refund

    org = org_factory()
    product = _make_product(org=org)
    order = _make_paid_order_with_payment(org=org, product=product, tender="cash")

    entry1 = record_refund(order=order, tender="cash")
    entry2 = record_refund(order=order, tender="cash")

    assert entry1.pk == entry2.pk
    assert AccountingEntry.objects.filter(
        org=org, entry_type=AccountingEntry.EntryType.REFUND_CASH
    ).count() == 1


# ---------------------------------------------------------------------------
# Tests: record_stock_return
# ---------------------------------------------------------------------------

def test_record_stock_return_creates_stock_receipt_entry(org_factory, lot_factory):
    """record_stock_return создаёт запись STOCK_RECEIPT."""
    from apps.accounting.logic.record_stock_return import record_stock_return
    from apps.inventory.services.deduct_stock import deduct_stock, restore_stock

    org = org_factory()
    product = _make_product(org=org)
    lot_factory(org=org, product=product, qty=Decimal("10.000"))

    deduct_stock(org=org, product=product, quantity=Decimal("1.000"), reason="order_paid")
    movement = restore_stock(org=org, product=product, quantity=Decimal("1.000"), reason="order_cancelled")

    entry = record_stock_return(movement=movement)

    assert entry.entry_type == AccountingEntry.EntryType.STOCK_RECEIPT
    assert entry.amount > 0


# ---------------------------------------------------------------------------
# Tests: refund_paid_order — полный flow
# ---------------------------------------------------------------------------

def test_refund_cash_order_writes_refund_cash_entry(org_factory, lot_factory):
    """refund_paid_order для cash-заказа → запись REFUND_CASH."""
    from apps.orders.logic.refund_order import refund_paid_order

    org = org_factory()
    product = _make_product(org=org)
    lot = lot_factory(org=org, product=product, qty=Decimal("10.000"))
    order = _make_paid_order_with_payment(org=org, product=product, tender="cash", lot=lot)

    refund_paid_order(order=order, actor=None)

    entry = AccountingEntry.objects.get(org=org, entry_type=AccountingEntry.EntryType.REFUND_CASH)
    assert entry.amount < 0


def test_refund_card_order_writes_refund_card_entry(org_factory, lot_factory):
    """refund_paid_order для card-заказа → запись REFUND_CARD."""
    from apps.orders.logic.refund_order import refund_paid_order

    org = org_factory()
    product = _make_product(org=org)
    lot = lot_factory(org=org, product=product, qty=Decimal("10.000"))
    order = _make_paid_order_with_payment(org=org, product=product, tender="card", lot=lot)

    refund_paid_order(order=order, actor=None)

    entry = AccountingEntry.objects.get(org=org, entry_type=AccountingEntry.EntryType.REFUND_CARD)
    assert entry.amount < 0


def test_refund_writes_stock_return_entry(org_factory, lot_factory):
    """refund_paid_order для не-prepared товара → запись STOCK_RECEIPT."""
    from apps.orders.logic.refund_order import refund_paid_order

    org = org_factory()
    product = _make_product(org=org, requires_preparation=False)
    lot = lot_factory(org=org, product=product, qty=Decimal("10.000"))
    order = _make_paid_order_with_payment(org=org, product=product, lot=lot)

    refund_paid_order(order=order, actor=None)

    assert AccountingEntry.objects.filter(
        org=org, entry_type=AccountingEntry.EntryType.STOCK_RECEIPT
    ).count() >= 1


def test_prepared_product_refund_no_stock_return_entry(org_factory):
    """Prepared-продукт при возврате не создаёт STOCK_RECEIPT."""
    from apps.orders.logic.refund_order import refund_paid_order

    org = org_factory()
    product = _make_product(org=org, name="Burger", requires_preparation=True)
    order = _make_paid_order_with_payment(org=org, product=product, tender="cash")

    refund_paid_order(order=order, actor=None)

    assert AccountingEntry.objects.filter(
        org=org, entry_type=AccountingEntry.EntryType.REFUND_CASH
    ).count() == 1
    assert AccountingEntry.objects.filter(
        org=org, entry_type=AccountingEntry.EntryType.STOCK_RECEIPT
    ).count() == 0
