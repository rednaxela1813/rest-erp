# tests/test_cashier_refund_cash_drawer.py

from decimal import Decimal
import pytest


from apps.cashier import views as cashier_views
from apps.orders.models import Order, OrderItem
from apps.payments.models import CashDrawerMovement, CashierSession, OrderPayment, Terminal
from apps.products.models import Product, TaxRate, Unit
from config.orgs.models import OrganizationMember
from apps.accounting.models import AccountingEntry


def _prepare_cashier_session(*, client, org, user) -> CashierSession:
    terminal = Terminal.objects.create(org=org, name="POS 1", code="pos-1")
    session = CashierSession.objects.create(
        org=org,
        terminal=terminal,
        cashier=user,
        cash_drawer_start=Decimal("100.00"),
    )
    session_data = client.session
    session_data[cashier_views.SESSION_ORG_ID] = str(org.public_id)
    session_data[cashier_views.SESSION_SESSION_ID] = session.id
    session_data[cashier_views.SESSION_CART] = {}
    session_data.save()
    return session


def _prepare_product(*, org) -> Product:
    from apps.inventory.services.receive_stock import receive_stock
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 23", rate=Decimal("23.00"))
    product = Product.objects.create(
        org=org, name="Cola", unit=unit, tax_rate=tax_rate, unit_price=Decimal("2.00"),
    )
    receive_stock(
        org=org, product=product,
        initial_qty=Decimal("10.000"), unit_cost=Decimal("1.00"), label_code="LOT-COLA",
    )
    return product


def _make_paid_order_with_cash_payment(*, org, product) -> Order:
    """Создаёт оплаченный заказ + захваченный cash-платёж, списывает сток."""
    from apps.inventory.services.deduct_stock import deduct_stock

    order = Order.objects.create(org=org, status=Order.STATUS_PAID)
    OrderItem.objects.create(
        order=order, product=product, product_name=product.name,
        qty=Decimal("1.000"), unit=product.unit,
        unit_price=Decimal("2.00"), tax_rate=product.tax_rate,
    )
    order.recompute_totals()
    order.save()

    OrderPayment.objects.create(
        org=org, order=order,
        tender=OrderPayment.Tender.CASH,
        status=OrderPayment.Status.CAPTURED,
        amount=order.total, currency="EUR", provider="manual",
    )
    deduct_stock(org=org, product=product, quantity=Decimal("1.000"), reason="order_paid")
    return order


@pytest.mark.django_db
def test_cash_refund_creates_cash_out_movement(client, user_factory, org_factory):
    """
    При возврате наличными кассир выдаёт деньги из ящика —
    должен создаться CashDrawerMovement типа CASH_OUT.
    """
    user = user_factory(email="cashier@example.com")
    org = org_factory(name="Test Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    session = _prepare_cashier_session(client=client, org=org, user=user)

    product = _prepare_product(org=org)
    order = _make_paid_order_with_cash_payment(org=org, product=product)

    resp = client.post(f"/cashier/orders/{order.public_id}/refund/")

    assert resp.status_code == 302  # redirect to cashier:home

    movement = CashDrawerMovement.objects.filter(
        session=session,
        movement_type=CashDrawerMovement.Type.CASH_OUT,
    ).first()
    assert movement is not None, "CASH_OUT movement should be created for cash refund"
    assert movement.amount == order.total
    assert str(order.public_id) in movement.reason


@pytest.mark.django_db
def test_cash_refund_reduces_drawer_total(client, user_factory, org_factory):
    """
    После возврата наличными остаток в ящике уменьшается на сумму возврата.
    """
    from apps.cashier.logic.session import cash_drawer_total as _cash_drawer_total

    user = user_factory(email="cashier2@example.com")
    org = org_factory(name="Test Org 2")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    session = _prepare_cashier_session(client=client, org=org, user=user)

    product = _prepare_product(org=org)
    order = _make_paid_order_with_cash_payment(org=org, product=product)

    drawer_before = _cash_drawer_total(session)

    client.post(f"/cashier/orders/{order.public_id}/refund/")

    session.refresh_from_db()
    drawer_after = _cash_drawer_total(session)

    assert drawer_after == drawer_before - order.total


@pytest.mark.django_db
def test_card_refund_does_not_create_cash_out_movement(client, user_factory, org_factory):
    """
    При возврате по карте ящик не трогаем — нет физического терминала.
    """
    from apps.inventory.services.deduct_stock import deduct_stock

    user = user_factory(email="cashier3@example.com")
    org = org_factory(name="Test Org 3")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    session = _prepare_cashier_session(client=client, org=org, user=user)

    product = _prepare_product(org=org)

    order = Order.objects.create(org=org, status=Order.STATUS_PAID)
    OrderItem.objects.create(
        order=order, product=product, product_name=product.name,
        qty=Decimal("1.000"), unit=product.unit,
        unit_price=Decimal("2.00"), tax_rate=product.tax_rate,
    )
    order.recompute_totals()
    order.save()
    OrderPayment.objects.create(
        org=org, order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=order.total, currency="EUR", provider="manual",
    )
    deduct_stock(org=org, product=product, quantity=Decimal("1.000"), reason="order_paid")

    client.post(f"/cashier/orders/{order.public_id}/refund/")

    cash_out_count = CashDrawerMovement.objects.filter(
        session=session,
        movement_type=CashDrawerMovement.Type.CASH_OUT,
    ).count()
    assert cash_out_count == 0, "Card refund must NOT create CASH_OUT movement"


"""Тест на правильность записи в базу при оплате наличными"""
@pytest.mark.django_db
def test_cash_payment_records_sale(client, user_factory, org_factory):
    from apps.accounting.models import AccountingEntry

    user = user_factory(email="cashier4@example.com")
    org = org_factory(name="Test Org 4")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    session = _prepare_cashier_session(client=client, org=org, user=user)
    product = _prepare_product(org=org)

    # Кладём товар в корзину
    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 1}
    session_data.save()

    # Делаем checkout наличными
    resp = client.post("/cashier/checkout/", {"tender": "cash"})
    assert resp.status_code == 302

    # Проверяем бухгалтерскую запись
    entry = AccountingEntry.objects.filter(
        org=org,
        entry_type=AccountingEntry.EntryType.SALE_CASH,
    ).first()
    assert entry is not None, "SALE_CASH entry should be created after cash payment"
    assert entry.amount == product.unit_price
    
    
    
    
