# apps/recipes/services/check_ingredients.py

from apps.products.models import Product


def has_enough_ingredients(product: Product) -> bool:
    """
    Проверяет достаточно ли ингредиентов на складе
    для приготовления одной единицы продукта по рецепту.

    # TODO: вариант Б — кэшировать результат на продукте
    # чтобы не делать запросы к базе при каждой загрузке меню
    """
    recipe = getattr(product, "recipe", None)
    if recipe is None:
        return True

    for ingredient in recipe.ingredients.all():
        stock = ingredient.product.stock_qty or 0
        needed = ingredient.quantity

        if stock < needed:
            return False

    return True
