import pytest

from apps.orders.models import Order
from apps.payments.models import OrderPayment
from apps.payments.providers.manual import ManualProvider
from apps.payments.providers.ekasa import EkasaProvider
from apps.payments.providers.registry import get_provider_for_payment


@pytest.mark.django_db
def test_registry_returns_ekasa_provider(org_factory):
    org = org_factory()
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        amount="5.00",
        currency="EUR",
        provider="ekasa",
    )

    provider = get_provider_for_payment(payment)
    assert isinstance(provider, EkasaProvider)


def test_ekasa_provider_requires_base_url(settings):
    # Empty base URL should fail fast so we don't attempt real device calls.
    settings.EKASA_BASE_URL = ""
    provider = EkasaProvider()

    with pytest.raises(RuntimeError, match="EKASA_BASE_URL"):
        provider.capture(payment=None, timeout_s=10)


@pytest.mark.django_db
def test_registry_falls_back_to_manual_provider_for_unknown_provider(org_factory):
    org = org_factory()
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        amount="5.00",
        currency="EUR",
        provider="unknown",
    )

    provider = get_provider_for_payment(payment)
    assert isinstance(provider, ManualProvider)


@pytest.mark.django_db
def test_manual_provider_capture_status_maps_failed_and_pending(org_factory):
    org = org_factory()
    order = Order.objects.create(org=org)
    provider = ManualProvider()

    failed_payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.FAILED,
        amount="5.00",
        currency="EUR",
        provider="manual",
    )
    pending_payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.PENDING,
        amount="5.00",
        currency="EUR",
        provider="manual",
    )

    assert provider.capture_status(payment=failed_payment, timeout_s=10) == {"status": "failed"}
    assert provider.capture_status(payment=pending_payment, timeout_s=10) == {"status": "pending"}
