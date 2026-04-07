import pytest
from decimal import Decimal

from apps.products.models import Product, TaxRate, Unit
from apps.recipes.services.check_ingredients import has_enough_ingredients
from tests.conftest import admin_client
from apps.recipes.models import Recipe, RecipeItem

pytestmark = pytest.mark.django_db


def test_prepared_product_visible_when_ingredients_available(admin_client, lot_factory):
    # создай бургер с рецептом и достаточным количеством ингредиентов
    # вызови has_enough_ingredients(burger)
    # проверь что вернулось True
    
    client, user, org = admin_client
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    
    bun = Product.objects.create(org=org, name="Bun", status=Product.STATUS_ACTIVE, product_type=Product.PRODUCT_TYPE_INGREDIENT, unit=unit, tax_rate=tax, unit_price=Decimal("0.50"))

    patty = Product.objects.create(org=org, name="Patty", status=Product.STATUS_ACTIVE, product_type=Product.PRODUCT_TYPE_INGREDIENT, unit=unit, tax_rate=tax, unit_price=Decimal("1.00"))
    
    burger = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE, product_type=Product.PRODUCT_TYPE_PREPARED, unit=unit, tax_rate=tax, unit_price=Decimal("5.00"))
    
    # добавляем рецепт для бургера
    recipe = Recipe.objects.create(org=org, name="Burger Recipe", product=burger)
    RecipeItem.objects.create(org=org, recipe=recipe, product=bun, quantity=Decimal("1"))
    RecipeItem.objects.create(org=org, recipe=recipe, product=patty, quantity=Decimal("1"))
    
    lot_factory(org=org, product=bun, qty=Decimal("10"))
    lot_factory(org=org, product=patty, qty=Decimal("10"))
    
    assert has_enough_ingredients(burger) is True

def test_prepared_product_hidden_when_ingredients_missing(admin_client, lot_factory):
    # создай бургер с рецептом но БЕЗ ингредиентов на складе
    # вызови has_enough_ingredients(burger)
    # проверь что вернулось False
    client, user, org = admin_client
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20%", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)
    
    bun = Product.objects.create(org=org, name="Bun", status=Product.STATUS_ACTIVE, product_type=Product.PRODUCT_TYPE_INGREDIENT, unit=unit, tax_rate=tax, unit_price=Decimal("0.50"))

    patty = Product.objects.create(org=org, name="Patty", status=Product.STATUS_ACTIVE, product_type=Product.PRODUCT_TYPE_INGREDIENT, unit=unit, tax_rate=tax, unit_price=Decimal("1.00"))
    
    burger = Product.objects.create(org=org, name="Burger", status=Product.STATUS_ACTIVE, product_type=Product.PRODUCT_TYPE_PREPARED, unit=unit, tax_rate=tax, unit_price=Decimal("5.00"))
    
    # добавляем рецепт для бургера
    recipe = Recipe.objects.create(org=org, name="Burger Recipe", product=burger)
    RecipeItem.objects.create(org=org, recipe=recipe, product=bun, quantity=Decimal("1"))
    RecipeItem.objects.create(org=org, recipe=recipe, product=patty, quantity=Decimal("1"))
    
    lot_factory(org=org, product=bun, qty=Decimal("10"))
    #lot_factory(org=org, product=patty, quantity=Decimal("10"), status="active")
    
    assert has_enough_ingredients(burger) is False