#project/backend/tests/recipes/test_recipe_stock_deduction.py
import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_prepared_product_deducts_ingredients(admin_client, lot_factory, payment_factory, capture_payment_api):
    client, user, org = admin_client
    
    from apps.products.models import Product, Unit, TaxRate
    from apps.recipes.models import Recipe, RecipeItem
    from apps.orders.models import Order
    from apps.inventory.models import StockLot
    
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="DPH 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    
    ingredient1 = Product.objects.create(org=org, name="Ingredient 1", status=Product.STATUS_ACTIVE, product_type=Product.PRODUCT_TYPE_INGREDIENT, unit=unit, tax_rate=tax, unit_price=Decimal("1.00"))
    ingredient2 = Product.objects.create(org=org, name="Ingredient 2", status=Product.STATUS_ACTIVE, product_type=Product.PRODUCT_TYPE_INGREDIENT, unit=unit, tax_rate=tax, unit_price=Decimal("2.00"))
    
    burger = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE, product_type=Product.PRODUCT_TYPE_PREPARED, unit=unit, tax_rate=tax, unit_price=Decimal("10.00"))
    
    lot_factory(org=org, product=ingredient1, qty=Decimal("10.000"))
    lot_factory(org=org, product=ingredient2, qty=Decimal("20.000"))
    
    
    recipe = Recipe.objects.create(org=org, name="Burger Recipe", product=burger)
    RecipeItem.objects.create(org=org, recipe=recipe, product=ingredient1, quantity=Decimal("2.000"))
    RecipeItem.objects.create(org=org, recipe=recipe, product=ingredient2, quantity=Decimal("3.000"))
    
    order = Order.objects.create(org=org)
    r1 = client.post(
        f"/api/v1/orders/{order.public_id}/items/",
        data={"product": str(burger.public_id), "quantity": "1", "unit": str(unit.public_id), "unit_price": "10.00", "tax_rate": str(tax.public_id)},
        content_type="application/json",
    )
    assert r1.status_code == 201        
    payment = payment_factory(order=order, org=org, amount=Decimal("10.00"))
    r2 = capture_payment_api(client, payment)
    assert r2.status_code == 200
    
    lot1 = StockLot.objects.get(org=org, product=ingredient1)
    lot2 = StockLot.objects.get(org=org, product=ingredient2)
    assert lot1.remaining_qty == Decimal("8.000")
    assert lot2.remaining_qty == Decimal("17.000")
    
    