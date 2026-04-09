from decimal import Decimal
import pytest
from apps.inventory.models import StockLot, StockMovement
from apps.inventory.services.deduct_stock import deduct_stock, restore_stock
from apps.inventory.services.receive_stock import receive_stock
from apps.products.models import Product, Unit, TaxRate


@pytest.mark.django_db
def test_restore_stock_increases_remaining_qty(org_factory):
    org = org_factory()
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    cola = Product.objects.create(
        org=org, name="Cola", unit=unit, tax_rate=tax_rate,
        unit_price=Decimal("2.00"), product_type=Product.PRODUCT_TYPE_SIMPLE,
        requires_preparation=False,
    )
    receive_stock(org=org, product=cola, initial_qty=Decimal("5.000"),
                  unit_cost=Decimal("1.00"), label_code="LOT-COLA")
    deduct_stock(org=org, product=cola, quantity=Decimal("2.000"), reason="order_paid")

    lot = StockLot.objects.get(org=org, product=cola)
    assert lot.remaining_qty == Decimal("3.000")

    restore_stock(org=org, product=cola, quantity=Decimal("1.000"), reason="order_cancelled")

    lot.refresh_from_db()
    assert lot.remaining_qty == Decimal("4.000"), (
        f"После возврата ожидалось 4.000, получено {lot.remaining_qty}"
    )


@pytest.mark.django_db
def test_restore_stock_creates_stock_movement_in(org_factory):
    org = org_factory()
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    cola = Product.objects.create(
        org=org, name="Cola", unit=unit, tax_rate=tax_rate,
        unit_price=Decimal("2.00"), product_type=Product.PRODUCT_TYPE_SIMPLE,
    )
    receive_stock(org=org, product=cola, initial_qty=Decimal("3.000"),
                  unit_cost=Decimal("1.00"), label_code="LOT-COLA-2")
    deduct_stock(org=org, product=cola, quantity=Decimal("1.000"), reason="order_paid")

    movements_before = StockMovement.objects.filter(org=org, product=cola).count()

    restore_stock(org=org, product=cola, quantity=Decimal("1.000"),
                  reason="order_cancelled", comment="test-order-id")

    movements_after = StockMovement.objects.filter(org=org, product=cola).count()
    assert movements_after == movements_before + 1, "restore_stock должен создавать StockMovement"

    last_movement = (
        StockMovement.objects.filter(org=org, product=cola).order_by("-created_at").first()
    )
    assert last_movement.movement_type == StockMovement.MovementType.IN
    assert last_movement.quantity == Decimal("1.000")
    assert last_movement.reason == "order_cancelled"


@pytest.mark.django_db
def test_restore_stock_on_depleted_lot_reactivates_it(org_factory):
    org = org_factory()
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    cola = Product.objects.create(
        org=org, name="Cola", unit=unit, tax_rate=tax_rate, unit_price=Decimal("2.00"),
    )
    receive_stock(org=org, product=cola, initial_qty=Decimal("1.000"),
                  unit_cost=Decimal("1.00"), label_code="LOT-COLA-3")
    deduct_stock(org=org, product=cola, quantity=Decimal("1.000"), reason="order_paid")

    lot = StockLot.objects.get(org=org, product=cola)
    assert lot.status == StockLot.Status.DEPLETED

    restore_stock(org=org, product=cola, quantity=Decimal("1.000"), reason="order_cancelled")

    lot.refresh_from_db()
    assert lot.remaining_qty == Decimal("1.000")
    assert lot.status == StockLot.Status.ACTIVE


@pytest.mark.django_db
def test_cancel_order_does_not_restore_prepared_product_stock(org_factory):
    from apps.orders.logic.cancel_order import cancel_order
    from apps.orders.models import Order, OrderItem

    org = org_factory()
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    burger = Product.objects.create(
        org=org, name="Burger", unit=unit, tax_rate=tax_rate,
        unit_price=Decimal("5.00"), product_type=Product.PRODUCT_TYPE_SIMPLE,
        requires_preparation=True,
    )
    receive_stock(org=org, product=burger, initial_qty=Decimal("1.000"),
                  unit_cost=Decimal("2.00"), label_code="LOT-BURGER")

    order = Order.objects.create(org=org, status=Order.STATUS_PAID)
    OrderItem.objects.create(
        order=order, product=burger, product_name=burger.name,
        qty=Decimal("1.000"), unit=unit, unit_price=Decimal("5.00"), tax_rate=tax_rate,
    )
    deduct_stock(org=org, product=burger, quantity=Decimal("1.000"), reason="order_paid")

    lot = StockLot.objects.get(org=org, product=burger)
    assert lot.remaining_qty == Decimal("0.000")

    cancel_order(order=order)

    lot.refresh_from_db()
    assert lot.remaining_qty == Decimal("0.000"), (
        f"Prepared-товар не должен возвращаться на склад, получено {lot.remaining_qty}"
    )
