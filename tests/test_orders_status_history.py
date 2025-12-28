import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_pay_order_creates_status_event(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order, OrderItem, OrderStatusEvent
    from apps.products.models import Product, Unit, TaxRate
    from apps.orders.logic.pay_order import pay_order

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Cola", status=Product.STATUS_ACTIVE, stock_qty=Decimal("10.000"))
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("2.000"),
        unit=unit,
        unit_price=Decimal("3.50"),
        tax_rate=tax,
    )

    pay_order(order=order, actor=user)

    ev = OrderStatusEvent.objects.get(order=order)
    assert ev.org == org
    assert ev.actor == user
    assert ev.from_status == Order.STATUS_DRAFT
    assert ev.to_status == Order.STATUS_PAID


@pytest.mark.django_db
def test_cancel_paid_order_creates_status_event(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order, OrderItem, OrderStatusEvent
    from apps.products.models import Product, Unit, TaxRate
    from apps.orders.logic.pay_order import pay_order
    from apps.orders.logic.cancel_order import cancel_order

    order = Order.objects.create(org=org)

    product = Product.objects.create(org=org, name="Cola", status=Product.STATUS_ACTIVE, stock_qty=Decimal("10.000"))
    unit = Unit.objects.create(org=org, name="pcs", status=Unit.STATUS_ACTIVE)
    tax = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"), status=TaxRate.STATUS_ACTIVE)

    OrderItem.objects.create(
        order=order,
        product=product,
        product_name=product.name,
        qty=Decimal("2.000"),
        unit=unit,
        unit_price=Decimal("3.50"),
        tax_rate=tax,
    )

    pay_order(order=order, actor=user)
    cancel_order(order=order, actor=user)

    events = list(OrderStatusEvent.objects.filter(order=order).order_by("created_at"))
    assert len(events) == 2

    assert events[0].from_status == Order.STATUS_DRAFT
    assert events[0].to_status == Order.STATUS_PAID

    assert events[1].from_status == Order.STATUS_PAID
    assert events[1].to_status == Order.STATUS_CANCELLED


@pytest.mark.django_db
def test_cancel_draft_order_creates_status_event(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order, OrderStatusEvent
    from apps.orders.logic.cancel_draft_order import cancel_draft_order

    order = Order.objects.create(org=org)
    cancel_draft_order(order=order, actor=user)

    ev = OrderStatusEvent.objects.get(order=order)
    assert ev.from_status == Order.STATUS_DRAFT
    assert ev.to_status == Order.STATUS_CANCELLED
    assert ev.actor == user
