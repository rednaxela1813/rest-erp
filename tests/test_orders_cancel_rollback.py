import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_cancel_order_rolls_back_stock_if_error_occurs_midway(admin_client, monkeypatch):
    """
    GIVEN:
        - Заказ оплачен, два разных продукта, у каждого своя партия
        - При оплате остатки списаны

    WHEN:
        - Во время cancel_order происходит ошибка при сохранении статуса заказа

    THEN:
        - transaction.atomic() откатывает всё
        - заказ остаётся paid
        - остатки в партиях не меняются
    """
    client, user, org = admin_client

    from apps.orders.logic.pay_order import pay_order
    from apps.orders.logic.cancel_order import cancel_order
    from apps.orders.models import Order, OrderItem
    from apps.products.models import Product, Unit, TaxRate
    from apps.inventory.models import StockLot
    from apps.inventory.services.receive_stock import receive_stock

    order = Order.objects.create(org=org)

    product_a = Product.objects.create(org=org, name="A", status=Product.STATUS_ACTIVE)
    product_b = Product.objects.create(org=org, name="B", status=Product.STATUS_ACTIVE)
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

    receive_stock(org=org, product=product_a, initial_qty=Decimal("10.000"), unit_cost=Decimal("1.00"), label_code="LOT-A")
    receive_stock(org=org, product=product_b, initial_qty=Decimal("10.000"), unit_cost=Decimal("1.00"), label_code="LOT-B")

    OrderItem.objects.create(
        order=order, product=product_a, product_name=product_a.name,
        qty=Decimal("2.000"), unit=unit, unit_price=Decimal("1.00"), tax_rate=tax,
    )
    OrderItem.objects.create(
        order=order, product=product_b, product_name=product_b.name,
        qty=Decimal("3.000"), unit=unit, unit_price=Decimal("1.00"), tax_rate=tax,
    )

    pay_order(order=order)

    lot_a = StockLot.objects.get(org=org, label_code="LOT-A")
    lot_b = StockLot.objects.get(org=org, label_code="LOT-B")
    assert lot_a.remaining_qty == Decimal("8.000")
    assert lot_b.remaining_qty == Decimal("7.000")

    # ломаем сохранение статуса заказа — это происходит в конце cancel_order
    # после того как restore_stock уже отработал
    original_save = Order.save
    calls = {"count": 0}

    def exploding_save(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("DB write failed")
        return original_save(self, *args, **kwargs)

    monkeypatch.setattr(Order, "save", exploding_save)

    with pytest.raises(RuntimeError):
        cancel_order(order=order)

    order.refresh_from_db()
    assert order.status == Order.STATUS_PAID

    lot_a.refresh_from_db()
    lot_b.refresh_from_db()
    assert lot_a.remaining_qty == Decimal("8.000")
    assert lot_b.remaining_qty == Decimal("7.000")