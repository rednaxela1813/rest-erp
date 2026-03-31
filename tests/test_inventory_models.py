from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.equipment.models import Equipment
from apps.inventory.models import StockLot, StockMovement, StorageLocation
from apps.partners.models import Partner
from apps.products.models import Product, TaxRate, Unit


pytestmark = pytest.mark.django_db


def _make_product(*, org, name="Cola") -> Product:
    unit = Unit.objects.create(org=org, name=f"{name} unit")
    tax_rate = TaxRate.objects.create(org=org, name=f"{name} tax", rate=Decimal("20.00"))
    return Product.objects.create(
        org=org,
        name=name,
        unit=unit,
        tax_rate=tax_rate,
        unit_price=Decimal("2.50"),
        stock_qty=Decimal("100.000"),
    )


def _make_storage_location(*, org, name="Shelf A") -> StorageLocation:
    equipment = Equipment.objects.create(org=org, name=f"{name} fridge")
    return StorageLocation.objects.create(org=org, name=name, equipment=equipment)


def _make_stock_lot(*, org, product, storage_location=None, supplier=None, **overrides) -> StockLot:
    return StockLot.objects.create(
        org=org,
        product=product,
        supplier=supplier,
        storage_location=storage_location,
        label_code=overrides.pop("label_code", "LOT-001"),
        batch_number=overrides.pop("batch_number", "BATCH-001"),
        initial_qty=overrides.pop("initial_qty", Decimal("10.000")),
        remaining_qty=overrides.pop("remaining_qty", Decimal("10.000")),
        unit_cost=overrides.pop("unit_cost", Decimal("1.20")),
        status=overrides.pop("status", StockLot.Status.ACTIVE),
        **overrides,
    )


def test_storage_location_name_must_be_unique_per_org(org_factory):
    org = org_factory(name="Main Org")
    _make_storage_location(org=org, name="Cold Room")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_storage_location(org=org, name="Cold Room")


def test_storage_location_same_name_is_allowed_in_different_orgs(org_factory):
    org_one = org_factory(name="Org One")
    org_two = org_factory(name="Org Two")

    first = _make_storage_location(org=org_one, name="Cold Room")
    second = _make_storage_location(org=org_two, name="Cold Room")

    assert first.name == second.name
    assert first.org_id != second.org_id


@pytest.mark.parametrize(
    ("initial_qty", "remaining_qty"),
    [
        (Decimal("0.000"), Decimal("0.000")),
        (Decimal("10.000"), Decimal("-1.000")),
        (Decimal("10.000"), Decimal("11.000")),
    ],
)
def test_stock_lot_quantity_constraints_are_enforced(org_factory, initial_qty, remaining_qty):
    org = org_factory()
    product = _make_product(org=org)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_stock_lot(
                org=org,
                product=product,
                initial_qty=initial_qty,
                remaining_qty=remaining_qty,
            )


def test_stock_movement_quantity_must_be_positive(org_factory):
    org = org_factory()
    product = _make_product(org=org)
    lot = _make_stock_lot(org=org, product=product)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            StockMovement.objects.create(
                org=org,
                product=product,
                lot=lot,
                movement_type=StockMovement.MovementType.OUT,
                quantity=Decimal("0.000"),
                unit_cost_snapshot=Decimal("1.20"),
            )


def test_stock_movement_is_ordered_newest_first(org_factory):
    org = org_factory()
    product = _make_product(org=org)
    lot = _make_stock_lot(org=org, product=product)

    first = StockMovement.objects.create(
        org=org,
        product=product,
        lot=lot,
        movement_type=StockMovement.MovementType.IN,
        quantity=Decimal("5.000"),
        unit_cost_snapshot=Decimal("1.20"),
        reason="receipt",
    )
    second = StockMovement.objects.create(
        org=org,
        product=product,
        lot=lot,
        movement_type=StockMovement.MovementType.OUT,
        quantity=Decimal("2.000"),
        unit_cost_snapshot=Decimal("1.20"),
        reason="sale",
    )

    movements = list(StockMovement.objects.filter(org=org))

    assert movements == [second, first]


def test_stock_lot_and_movement_protect_related_objects(org_factory):
    org = org_factory()
    product = _make_product(org=org)
    supplier = Partner.objects.create(org=org, name="Best Supplier")
    storage_location = _make_storage_location(org=org, name="Freezer")
    lot = _make_stock_lot(
        org=org,
        product=product,
        supplier=supplier,
        storage_location=storage_location,
    )
    StockMovement.objects.create(
        org=org,
        product=product,
        lot=lot,
        movement_type=StockMovement.MovementType.IN,
        quantity=Decimal("10.000"),
        unit_cost_snapshot=Decimal("1.20"),
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            product.delete()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            lot.delete()


def test_stock_lot_string_representation_contains_product_and_quantities(org_factory):
    org = org_factory()
    product = _make_product(org=org, name="Tomatoes")
    lot = _make_stock_lot(
        org=org,
        product=product,
        label_code="LOT-TOM-1",
        initial_qty=Decimal("8.000"),
        remaining_qty=Decimal("5.500"),
    )

    assert str(lot) == "Tomatoes - LOT-TOM-1 (5.500/8.000)"
