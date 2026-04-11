# tests/test_kitchen_tickets_prepared.py
"""
Tests that PRODUCT_TYPE_PREPARED products (e.g. burgers with recipes)
correctly create KitchenTickets for the product itself — not for ingredients.
"""
import pytest
from decimal import Decimal

from apps.orders.models import KitchenTicket, Order, OrderItem
from apps.payments.models import OrderPayment
from apps.products.models import Product, TaxRate, Unit

pytestmark = pytest.mark.django_db


def _make_ingredient(*, org, name="Bun"):
    unit = Unit.objects.create(org=org, name=f"{name}-unit")
    tax = TaxRate.objects.create(org=org, name=f"{name}-tax", rate=Decimal("23.00"))
    return Product.objects.create(
        org=org, name=name,
        product_type=Product.PRODUCT_TYPE_INGREDIENT,
        unit=unit, tax_rate=tax, unit_price=Decimal("0.50"),
    )


def _make_prepared_product(*, org, name="Burger", ingredients=None):
    from apps.recipes.models import Recipe, RecipeItem
    unit = Unit.objects.create(org=org, name=f"{name}-unit")
    tax = TaxRate.objects.create(org=org, name=f"{name}-tax", rate=Decimal("23.00"))
    product = Product.objects.create(
        org=org, name=name,
        product_type=Product.PRODUCT_TYPE_PREPARED,
        requires_preparation=True,
        unit=unit, tax_rate=tax, unit_price=Decimal("7.00"),
    )
    recipe = Recipe.objects.create(org=org, product=product)
    for ingredient, qty in (ingredients or []):
        RecipeItem.objects.create(org=org, recipe=recipe, product=ingredient, quantity=qty)
    return product


def _make_paid_order_with_payment(*, org, product, qty=Decimal("1.000")):
    """Создаёт заказ в статусе DRAFT + захваченный платёж."""
    order = Order.objects.create(org=org, status=Order.STATUS_DRAFT)
    OrderItem.objects.create(
        order=order, product=product, product_name=product.name,
        qty=qty, unit=product.unit,
        unit_price=product.unit_price, tax_rate=product.tax_rate,
    )
    order.recompute_totals()
    order.save()
    OrderPayment.objects.create(
        org=org, order=order,
        tender=OrderPayment.Tender.CASH,
        status=OrderPayment.Status.CAPTURED,
        amount=order.total, currency="EUR", provider="manual",
    )
    return order


def test_prepared_product_creates_kitchen_ticket_for_itself(
    org_factory, lot_factory
):
    """
    Бургер (PRODUCT_TYPE_PREPARED) при оплате должен создать KitchenTicket
    для самого бургера — не для ингредиентов.
    """
    from apps.orders.logic.finalize_paid_order import finalize_paid_order

    org = org_factory()
    bun = _make_ingredient(org=org, name="Bun")
    patty = _make_ingredient(org=org, name="Patty")
    lot_factory(org=org, product=bun, qty=Decimal("10.000"))
    lot_factory(org=org, product=patty, qty=Decimal("10.000"))

    burger = _make_prepared_product(
        org=org, name="Burger",
        ingredients=[(bun, Decimal("1.000")), (patty, Decimal("1.000"))],
    )
    order = _make_paid_order_with_payment(org=org, product=burger)

    finalize_paid_order(order=order, actor=None)

    # KitchenTicket должен быть для бургера
    ticket = KitchenTicket.objects.filter(order=order, product=burger).first()
    assert ticket is not None, "KitchenTicket for burger must be created"
    assert ticket.qty == Decimal("1.000")
    assert ticket.status == KitchenTicket.Status.PENDING

    # KitchenTicket НЕ должен быть для ингредиентов
    assert not KitchenTicket.objects.filter(order=order, product=bun).exists()
    assert not KitchenTicket.objects.filter(order=order, product=patty).exists()


def test_prepared_product_ingredients_deducted_from_stock(
    org_factory, lot_factory
):
    """
    При оплате бургера ингредиенты списываются со склада.
    """
    from apps.inventory.models import StockLot
    from apps.orders.logic.finalize_paid_order import finalize_paid_order

    org = org_factory()
    bun = _make_ingredient(org=org, name="Bun2")
    lot_factory(org=org, product=bun, qty=Decimal("5.000"))

    burger = _make_prepared_product(
        org=org, name="Burger2",
        ingredients=[(bun, Decimal("2.000"))],
    )
    order = _make_paid_order_with_payment(org=org, product=burger, qty=Decimal("1.000"))

    finalize_paid_order(order=order, actor=None)

    lot = StockLot.objects.get(org=org, product=bun)
    assert lot.remaining_qty == Decimal("3.000"), "2 buns should be deducted"
