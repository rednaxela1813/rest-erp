from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounting.models import AccountingEntry
from apps.cashier import views as cashier_views
from apps.orders.models import Order
from apps.payments.models import CashierSession, DeviceCommand, OrderPayment, Terminal
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
    from apps.inventory.services.receive_stock import receive_stock

    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    product = Product.objects.create(
        org=org,
        name="Burger",
        unit=unit,
        tax_rate=tax_rate,
        unit_price=Decimal("5.00"),
    )
    receive_stock(
        org=org, product=product, initial_qty=Decimal("10.000"), unit_cost=Decimal("1.00"), label_code="LOT-BURGER"
    )
    return product


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
    fingerprint = cashier_views.cart_fingerprint(cart={str(product.id): 1}, tender=OrderPayment.Tender.CARD)
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


@pytest.mark.django_db
def test_confirm_cash_enqueues_fiscal_device_commands(cashier_client):
    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    product = _prepare_product(org=org)

    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 1}
    session_data.save()

    response = client.post("/cashier/checkout/", data={"tender": "cash"})
    assert response.status_code == 302

    payment = OrderPayment.objects.get(org=org)
    confirm_resp = client.post(f"/cashier/payments/{payment.public_id}/confirm/cash/")
    assert confirm_resp.status_code == 302

    command_types = set(DeviceCommand.objects.filter(payment=payment).values_list("command_type", flat=True))
    assert command_types == {
        DeviceCommand.Type.FISCALIZE_SALE,
        DeviceCommand.Type.PRINT_RECEIPT,
    }


@pytest.mark.django_db
def test_checkout_cash_auto_confirms_payment(cashier_client):
    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    product = _prepare_product(org=org)

    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 1}
    session_data.save()

    response = client.post("/cashier/checkout/", data={"tender": "cash"})
    assert response.status_code == 302

    payment = OrderPayment.objects.get(org=org)
    assert payment.status == OrderPayment.Status.CAPTURED


@pytest.mark.django_db
def test_checkout_cash_with_ekasa_keeps_order_unpaid_until_fiscal_confirmation(cashier_client, settings):
    settings.EKASA_ENABLED = True

    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    product = _prepare_product(org=org)

    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 1}
    session_data.save()

    response = client.post("/cashier/checkout/", data={"tender": "cash"})
    assert response.status_code == 302

    payment = OrderPayment.objects.get(org=org)
    order = payment.order
    order.refresh_from_db()

    assert payment.status == OrderPayment.Status.CAPTURED
    assert payment.fiscal_status == OrderPayment.FiscalStatus.PENDING
    assert order.status == Order.STATUS_DRAFT
    assert (
        AccountingEntry.objects.filter(
            org=org,
            entry_type__in=[
                AccountingEntry.EntryType.SALE_CASH,
                AccountingEntry.EntryType.SALE_CARD,
            ],
        ).count()
        == 0
    )


@pytest.mark.django_db
def test_checkout_card_auto_confirms_payment(cashier_client):
    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    product = _prepare_product(org=org)

    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 1}
    session_data.save()

    response = client.post("/cashier/checkout/", data={"tender": "card"})
    assert response.status_code == 302

    payment = OrderPayment.objects.get(org=org)
    assert payment.status == OrderPayment.Status.CAPTURED


@pytest.mark.django_db
def test_checkout_with_invalid_product_config_does_not_create_empty_draft(cashier_client):
    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    product = Product.objects.create(
        org=org,
        name="Broken product",
        unit=None,
        tax_rate=None,
        unit_price=Decimal("5.00"),
    )

    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 1}
    session_data.save()

    response = client.post("/cashier/checkout/", data={"tender": "cash"})
    assert response.status_code == 302
    assert response.url == "/cashier/"
    assert Order.objects.filter(org=org, status=Order.STATUS_DRAFT).count() == 0
    assert OrderPayment.objects.filter(org=org).count() == 0


@pytest.mark.django_db
def test_cashier_home_hides_products_missing_unit_or_tax_rate(cashier_client):
    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    sellable = _prepare_product(org=org)
    Product.objects.create(
        org=org,
        name="Broken product",
        unit=None,
        tax_rate=None,
        unit_price=Decimal("5.00"),
    )

    response = client.get("/cashier/")

    assert response.status_code == 200
    content = response.content.decode()
    assert sellable.name in content
    assert "Broken product" not in content


@pytest.mark.django_db
def test_cart_add_rejects_products_missing_unit_or_tax_rate(cashier_client):
    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    broken = Product.objects.create(
        org=org,
        name="Broken product",
        unit=None,
        tax_rate=None,
        unit_price=Decimal("5.00"),
    )

    response = client.post(f"/cashier/cart/add/{broken.id}/")

    assert response.status_code == 200
    assert b"cannot be sold in cashier until unit and tax rate are set" in response.content
    assert client.session[cashier_views.SESSION_CART] == {}


@pytest.mark.django_db
def test_cart_add_barcode_rejects_products_missing_unit_or_tax_rate(cashier_client):
    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    Product.objects.create(
        org=org,
        name="Broken product",
        barcode="12345",
        unit=None,
        tax_rate=None,
        unit_price=Decimal("5.00"),
    )

    response = client.post("/cashier/cart/add-barcode/", data={"barcode": "12345"})

    assert response.status_code == 200
    assert b"cannot be sold in cashier until unit and tax rate are set" in response.content
    assert client.session[cashier_views.SESSION_CART] == {}


@pytest.mark.django_db
def test_retry_fiscal_rebuilds_payload_and_requeues_failed_command(cashier_client):
    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    product = _prepare_product(org=org)
    product.tax_rate.rate = Decimal("10.00")
    product.tax_rate.save(update_fields=["rate"])

    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 1}
    session_data.save()

    response = client.post("/cashier/checkout/", data={"tender": "cash"})
    assert response.status_code == 302
    payment = OrderPayment.objects.get(org=org)

    command = DeviceCommand.objects.get(payment=payment, command_type=DeviceCommand.Type.FISCALIZE_SALE)
    command.status = DeviceCommand.Status.FAILED
    command.last_error = "vat rate rejected"
    command.save(update_fields=["status", "last_error", "updated_at"])
    payment.fiscal_status = OrderPayment.FiscalStatus.FAILED
    payment.failure_reason = "vat rate rejected"
    payment.save(update_fields=["fiscal_status", "failure_reason", "updated_at"])

    product.tax_rate.rate = Decimal("20.00")
    product.tax_rate.save(update_fields=["rate"])

    retry_resp = client.post(f"/cashier/payments/{payment.public_id}/retry-fiscal/")
    assert retry_resp.status_code == 302

    command.refresh_from_db()
    payment.refresh_from_db()
    assert command.status == DeviceCommand.Status.PENDING
    assert command.last_error == ""
    assert command.payload["items"][0]["tax_rate"] == "20.00"
    assert payment.fiscal_status == OrderPayment.FiscalStatus.PENDING
    assert payment.failure_reason == ""


@pytest.mark.django_db
def test_payment_status_recreates_missing_fiscal_command(cashier_client, settings):
    settings.EKASA_ENABLED = True

    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    product = _prepare_product(org=org)

    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 1}
    session_data.save()

    response = client.post("/cashier/checkout/", data={"tender": "cash"})
    assert response.status_code == 302

    payment = OrderPayment.objects.get(org=org)
    DeviceCommand.objects.filter(
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
    ).delete()

    status_resp = client.get(f"/cashier/payments/{payment.public_id}/status/")
    assert status_resp.status_code == 200
    assert DeviceCommand.objects.filter(
        payment=payment,
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
    ).exists()


@pytest.mark.django_db
def test_payment_status_marks_failed_when_inline_fiscal_processing_crashes(
    cashier_client,
    monkeypatch,
    settings,
):
    settings.EKASA_ENABLED = True

    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    product = _prepare_product(org=org)

    session_data = client.session
    session_data[cashier_views.SESSION_CART] = {str(product.id): 1}
    session_data.save()

    response = client.post("/cashier/checkout/", data={"tender": "cash"})
    assert response.status_code == 302

    payment = OrderPayment.objects.get(org=org)

    class DummyTask:
        @staticmethod
        def run(*, org_id: int, limit: int):
            raise RuntimeError("ekasa offline")

    monkeypatch.setattr("apps.payments.tasks.process_device_commands_ekasa", DummyTask)

    status_resp = client.get(f"/cashier/payments/{payment.public_id}/status/")
    assert status_resp.status_code == 200

    payment.refresh_from_db()
    assert payment.fiscal_status == OrderPayment.FiscalStatus.FAILED
    assert payment.failure_reason == "ekasa offline"


@pytest.mark.django_db
def test_cashier_product_list_renders_product_image(cashier_client):
    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    product = _prepare_product(org=org)
    product.image_url = "https://example.com/images/burger.jpg"
    product.save(update_fields=["image_url"])

    response = client.get("/cashier/products/")

    assert response.status_code == 200
    content = response.content.decode()
    assert 'src="https://example.com/images/burger.jpg"' in content
    assert 'alt="Burger"' in content


@pytest.mark.django_db
def test_cashier_product_list_prefers_uploaded_image_over_url(cashier_client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path

    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)
    product = _prepare_product(org=org)
    product.image_url = "https://example.com/images/url-burger.jpg"
    product.image = SimpleUploadedFile(
        "burger.png",
        (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        content_type="image/png",
    )
    product.save(update_fields=["image_url", "image"])

    response = client.get("/cashier/products/")

    assert response.status_code == 200
    content = response.content.decode()
    assert 'src="/media/products/' in content
    assert "url-burger.jpg" not in content


@pytest.mark.django_db
def test_cashier_product_list_hides_simple_product_without_stock_lot(cashier_client):
    client, user, org = cashier_client
    _prepare_cashier_session(client=client, org=org, user=user)

    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    Product.objects.create(
        org=org,
        name="Invisible Burger",
        unit=unit,
        tax_rate=tax_rate,
        unit_price=Decimal("5.00"),
    )

    response = client.get("/cashier/products/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Invisible Burger" not in content
