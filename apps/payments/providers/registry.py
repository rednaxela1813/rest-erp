from __future__ import annotations

from apps.payments.providers.manual import ManualProvider
from apps.payments.providers.ekasa import EkasaProvider


_PROVIDERS = {
    "manual": ManualProvider(),
    "ekasa": EkasaProvider(),
}


def get_provider_for_payment(payment):
    return _PROVIDERS.get(payment.provider, _PROVIDERS["manual"])
