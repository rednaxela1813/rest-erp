from __future__ import annotations

from apps.payments.providers.manual import ManualProvider


_PROVIDERS = {
    "manual": ManualProvider(),
}


def get_provider_for_payment(payment):
    return _PROVIDERS.get(payment.provider, _PROVIDERS["manual"])
