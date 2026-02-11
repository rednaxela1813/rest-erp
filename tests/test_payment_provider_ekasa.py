import pytest

from apps.orders.models import Order
from apps.payments.models import OrderPayment
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
