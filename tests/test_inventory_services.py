from decimal import Decimal

import pytest
from django.db import transaction

from apps.equipment.models import Equipment
from apps.inventory.exceptions import InsufficientStock, LotNotAvailable, LotNotFound
from apps.inventory.models import StockLot, StockMovement
from apps.inventory.services.issue_stock import issue_by_scanned_lot
from apps.inventory.services.receive_stock import receive_stock
from apps.products.models import Product, TaxRate, Unit


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_product(*, org, name="Cola") -> Product:
    unit = Unit.objects.create(org=org, name=f"{name} unit")
    tax_rate = TaxRate.objects.create(org=org, name=f"{name} tax", rate=Decimal("20.00"))
    return Product.objects.create(
        org=org,
        name=name,
        unit=unit,
        tax_rate=tax_rate,
        unit_price=Decimal("2.50"),
    )


# ---------------------------------------------------------------------------
# receive_stock
# ---------------------------------------------------------------------------

def test_receive_stock_creates_lot_and_movement(org_factory):
    org = org_factory()
    product = _make_product(org=org)

    lot, movement = receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.20"),
        label_code="LOT-001",
    )

    assert lot.pk is not None
    assert lot.initial_qty == Decimal("10.000")
    assert lot.remaining_qty == Decimal("10.000")
    assert lot.status == StockLot.Status.ACTIVE

    assert movement.pk is not None
    assert movement.movement_type == StockMovement.MovementType.IN
    assert movement.quantity == Decimal("10.000")
    assert movement.lot == lot
    assert movement.product == product


def test_receive_stock_remaining_qty_always_equals_initial(org_factory):
    org = org_factory()
    product = _make_product(org=org)

    lot, _ = receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("5.000"),
        unit_cost=Decimal("2.00"),
    )

    assert lot.remaining_qty == lot.initial_qty


def test_receive_stock_movement_snapshots_unit_cost(org_factory):
    org = org_factory()
    product = _make_product(org=org)

    _, movement = receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("3.75"),
    )

    assert movement.unit_cost_snapshot == Decimal("3.75")


# ---------------------------------------------------------------------------
# issue_by_scanned_lot
# ---------------------------------------------------------------------------

def test_issue_reduces_remaining_qty_and_creates_movement(org_factory):
    org = org_factory()
    product = _make_product(org=org)

    lot, _ = receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.20"),
        label_code="LOT-001",
    )

    lot_after, movement = issue_by_scanned_lot(
        org=org,
        label_code="LOT-001",
        quantity=Decimal("3.000"),
    )

    assert lot_after.remaining_qty == Decimal("7.000")
    assert lot_after.status == StockLot.Status.ACTIVE

    assert movement.movement_type == StockMovement.MovementType.OUT
    assert movement.quantity == Decimal("3.000")
    assert movement.lot == lot_after
    assert movement.product == product


def test_issue_full_quantity_marks_lot_depleted(org_factory):
    org = org_factory()
    product = _make_product(org=org)

    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("5.000"),
        unit_cost=Decimal("1.00"),
        label_code="LOT-FULL",
    )

    lot_after, _ = issue_by_scanned_lot(
        org=org,
        label_code="LOT-FULL",
        quantity=Decimal("5.000"),
    )

    assert lot_after.remaining_qty == Decimal("0.000")
    assert lot_after.status == StockLot.Status.DEPLETED


def test_issue_raises_if_quantity_exceeds_remaining(org_factory):
    org = org_factory()
    product = _make_product(org=org)

    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("3.000"),
        unit_cost=Decimal("1.00"),
        label_code="LOT-SMALL",
    )

    with pytest.raises(InsufficientStock):
        issue_by_scanned_lot(
            org=org,
            label_code="LOT-SMALL",
            quantity=Decimal("5.000"),
        )


def test_issue_raises_if_lot_not_found(org_factory):
    org = org_factory()

    with pytest.raises(LotNotFound):
        issue_by_scanned_lot(
            org=org,
            label_code="NONEXISTENT",
            quantity=Decimal("1.000"),
        )


def test_issue_raises_if_lot_is_depleted(org_factory):
    org = org_factory()
    product = _make_product(org=org)

    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("2.000"),
        unit_cost=Decimal("1.00"),
        label_code="LOT-DEP",
    )

    issue_by_scanned_lot(
        org=org,
        label_code="LOT-DEP",
        quantity=Decimal("2.000"),
    )

    with pytest.raises(LotNotAvailable):
        issue_by_scanned_lot(
            org=org,
            label_code="LOT-DEP",
            quantity=Decimal("1.000"),
        )


def test_issue_raises_if_lot_is_archived(org_factory):
    org = org_factory()
    product = _make_product(org=org)

    lot, _ = receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("5.000"),
        unit_cost=Decimal("1.00"),
        label_code="LOT-ARCH",
    )
    lot.status = StockLot.Status.ARCHIVED
    lot.save(update_fields=["status", "updated_at"])

    with pytest.raises(LotNotAvailable):
        issue_by_scanned_lot(
            org=org,
            label_code="LOT-ARCH",
            quantity=Decimal("1.000"),
        )


def test_issue_does_not_affect_other_orgs_lot(org_factory):
    org_a = org_factory(name="Org A")
    org_b = org_factory(name="Org B")
    product_a = _make_product(org=org_a)

    receive_stock(
        org=org_a,
        product=product_a,
        initial_qty=Decimal("10.000"),
        unit_cost=Decimal("1.00"),
        label_code="LOT-SHARED-CODE",
    )

    with pytest.raises(LotNotFound):
        issue_by_scanned_lot(
            org=org_b,
            label_code="LOT-SHARED-CODE",
            quantity=Decimal("1.000"),
        )


def test_insufficient_stock_does_not_modify_lot(org_factory):
    org = org_factory()
    product = _make_product(org=org)

    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("3.000"),
        unit_cost=Decimal("1.00"),
        label_code="LOT-SAFE",
    )

    with pytest.raises(InsufficientStock):
        issue_by_scanned_lot(
            org=org,
            label_code="LOT-SAFE",
            quantity=Decimal("99.000"),
        )

    lot = StockLot.objects.get(org=org, label_code="LOT-SAFE")
    assert lot.remaining_qty == Decimal("3.000")
    assert lot.status == StockLot.Status.ACTIVE
    