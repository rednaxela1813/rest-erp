import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_pay_order_rolls_back_stock_if_error_occurs_midway(admin_client, monkeypatch):
    """
    GIVEN:
        - Заказ draft с двумя разными продуктами
        - У каждого продукта своя партия

    WHEN:
        - Во время оплаты ошибка после списания из первой партии

    THEN:
        - transaction.atomic() откатывает всё
        - заказ остаётся draft
        - остатки в обеих партиях не меняются
    """
    client, user, org = admin_client

    from apps.orders.models import Order, OrderItem
    from apps.products.models import Product, Unit, TaxRate
    from apps.inventory.models import StockLot
    from apps.inventory.services.receive_stock import receive_stock
    from apps.orders.logic.pay_order import pay_order

    order = Order.objects.create(org=org)

    product_a = Product.objects.create(org=org, name="A", status="active")
    product_b = Product.objects.create(org=org, name="B", status="active")
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("0.20"))

    receive_stock(
        org=org, product=product_a, initial_qty=Decimal("10.000"), unit_cost=Decimal("1.00"), label_code="LOT-A"
    )
    receive_stock(
        org=org, product=product_b, initial_qty=Decimal("10.000"), unit_cost=Decimal("1.00"), label_code="LOT-B"
    )

    OrderItem.objects.create(
        order=order,
        product=product_a,
        product_name=product_a.name,
        qty=Decimal("2.000"),
        unit=unit,
        unit_price=Decimal("1.00"),
        tax_rate=tax_rate,
    )
    OrderItem.objects.create(
        order=order,
        product=product_b,
        product_name=product_b.name,
        qty=Decimal("3.000"),
        unit=unit,
        unit_price=Decimal("1.00"),
        tax_rate=tax_rate,
    )

    # ломаем второй вызов StockLot.save (первый lot сохранится, второй упадёт)
    original_save = StockLot.save
    calls = {"count": 0}

    def exploding_save(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("DB write failed")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(StockLot, "save", exploding_save)

    with pytest.raises(RuntimeError, match="DB write failed"):
        pay_order(order=order)

    order.refresh_from_db()
    assert order.status == Order.STATUS_DRAFT

    lot_a = StockLot.objects.get(org=org, label_code="LOT-A")
    lot_b = StockLot.objects.get(org=org, label_code="LOT-B")
    assert lot_a.remaining_qty == Decimal("10.000")
    assert lot_b.remaining_qty == Decimal("10.000")
