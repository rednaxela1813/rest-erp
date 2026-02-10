from decimal import Decimal

import pytest

from apps.cashier import views as cashier_views
from apps.payments.models import CashierSession, OrderPayment, Terminal
from apps.products.models import Product, TaxRate, Unit
from config.orgs.models import OrganizationMember


@pytest.fixture
def cashier_client(client, user_factory, org_factory):
    user = user_factory(email="cashier@example.com")
    org = org_factory(name="Cashier Org")
    OrganizationMember.objects.create(org=org, user=user, role="member")
    client.force_login(user)
    return client, user, org


def _prepare_cashier_session(*, client, org, user) -> CashierSession:
    terminal = Terminal.objects.create(org=org, name="POS 1", code="pos-1")
    session = CashierSession.objects.create(
        org=org,
        terminal=terminal,
        cashier=user,
        cash_drawer_start=Decimal("0.00"),
    )
    session_data = client.session
    session_data[cashier_views.SESSION_ORG_ID] = str(org.public_id)
    session_data[cashier_views.SESSION_SESSION_ID] = session.id
    session_data[cashier_views.SESSION_CART] = {}
    session_data.save()
    return session


def _prepare_product(*, org) -> Product:
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    return Product.objects.create(
        org=org,
        name="Burger",
        unit=unit,
        tax_rate=tax_rate,
        unit_price=Decimal("5.00"),
    )


@pytest.mark.django_db
def test_checkout_generates_idempotency_key_and_persists(cashier_client):
    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    product = _prepare_product(org=org)

    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 1}
    session_data.save()

    response = client.post("/cashier/checkout/", data={"tender": "card"})
    assert response.status_code == 302

    payment = OrderPayment.objects.get(org=org)
    assert payment.idempotency_key
    assert len(payment.idempotency_key) == 32

    idempotency_map = client.session.get(cashier_views.SESSION_CHECKOUT_IDEMPOTENCY)
    assert isinstance(idempotency_map, dict)
    fingerprint = cashier_views._cart_fingerprint(
        cart={str(product.id): 1}, tender=OrderPayment.Tender.CARD
    )
    assert idempotency_map.get(fingerprint) == payment.idempotency_key


@pytest.mark.django_db
def test_checkout_reuses_payment_for_same_cart_and_tender(cashier_client):
    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    product = _prepare_product(org=org)

    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 1}
    session_data.save()

    response_1 = client.post("/cashier/checkout/", data={"tender": "card"})
    assert response_1.status_code == 302
    payment = OrderPayment.objects.get(org=org)

    # Simulate a повторный checkout с тем же cart (без сброса idempotency).
    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 1}
    session_data.save()

    response_2 = client.post("/cashier/checkout/", data={"tender": "card"})
    assert response_2.status_code == 302

    assert OrderPayment.objects.filter(org=org).count() == 1
    assert response_2.url == f"/cashier/payments/{payment.public_id}/"


@pytest.mark.django_db
def test_checkout_idempotency_resets_on_cart_change(cashier_client):
    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    product = _prepare_product(org=org)

    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 1}
    session_data.save()

    response_1 = client.post("/cashier/checkout/", data={"tender": "cash"})
    assert response_1.status_code == 302
    payment_1 = OrderPayment.objects.get(org=org)

    # Change cart via UI endpoint (resets idempotency map).
    client.post(f"/cashier/cart/add/{product.id}/")

    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 2}
    session_data.save()

    response_2 = client.post("/cashier/checkout/", data={"tender": "cash"})
    assert response_2.status_code == 302

    assert OrderPayment.objects.filter(org=org).count() == 2
    payment_2 = OrderPayment.objects.exclude(id=payment_1.id).get(org=org)
    assert payment_1.idempotency_key != payment_2.idempotency_key
