from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum

from apps.products.models import Product
from apps.recipes.services.check_ingredients import has_enough_ingredients
from config.orgs.models import Organization


def get_products(org: Organization | None, query: str = "") -> list[Product]:
    """
    Возвращает продукты доступные для продажи:
    - только активные, с unit и tax_rate, не ингредиенты
    - для PREPARED: проверяем наличие ингредиентов через has_enough_ingredients
    - для остальных: проверяем stock_qty > 0
    """
    if not org:
        return Product.objects.none()

    qs = (
        Product.objects.filter(
            org=org,
            status=Product.STATUS_ACTIVE,
            unit__isnull=False,
            tax_rate__isnull=False,
        )
        .exclude(product_type=Product.PRODUCT_TYPE_INGREDIENT)
        .annotate(
            stock_qty_annotated=Sum(
                "stock_lots__remaining_qty",
                filter=Q(stock_lots__status="active"),
            )
        )
        .prefetch_related("recipe__ingredients__product__stock_lots")
        .order_by("name")
    )
    if query:
        qs = qs.filter(name__icontains=query)

    result = []
    for product in qs:
        if product.product_type == Product.PRODUCT_TYPE_PREPARED:
            if has_enough_ingredients(product):
                result.append(product)
        else:
            stock_qty = product.stock_qty_annotated or Decimal("0.000")
            if stock_qty > 0:
                result.append(product)
    return result
