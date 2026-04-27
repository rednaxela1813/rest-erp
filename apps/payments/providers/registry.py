# rest-erp/apps/payments/providers/registry.py
from __future__ import annotations

from apps.payments.providers.manual import ManualProvider
from apps.payments.providers.ekasa import EkasaProvider
from apps.payments.providers.nexo import NexoProvider


_PROVIDERS = {
    "manual": ManualProvider(),
    "ekasa": EkasaProvider(),
    "nexo": NexoProvider(),
}


def get_provider_for_payment(payment):
    return _PROVIDERS.get(payment.provider, _PROVIDERS["manual"])
