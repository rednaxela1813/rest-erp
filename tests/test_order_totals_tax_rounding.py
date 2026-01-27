from decimal import Decimal

import pytest

from apps.orders.models import Order, OrderItem
from apps.products.models import TaxRate, Unit


@pytest.mark.django_db
def test_order_totals_round_tax_per_line(org_factory):
    org = org_factory()
    unit = Unit.objects.create(org=org, name="pc")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))

    order = Order.objects.create(org=org)

    for _ in range(2):
        OrderItem.objects.create(
            order=order,
            product_name="Test item",
            qty=Decimal("1.000"),
            unit=unit,
            unit_price=Decimal("0.04"),
            tax_rate=tax_rate,
        )

    order.recompute_totals()

    assert order.subtotal == Decimal("0.08")
    assert order.tax_total == Decimal("0.02")
    assert order.total == Decimal("0.08")
