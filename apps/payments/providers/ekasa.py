from __future__ import annotations

from django.conf import settings

from apps.payments.providers.base import BasePaymentProvider


class EkasaProvider(BasePaymentProvider):
    """
    Skeleton adapter for NineDigit eKasa Web API.
    Stage 1: config validation + explicit "not implemented" behavior.
    """

    def __init__(self, *, base_url: str | None = None, api_key: str | None = None, timeout_s: int | None = None):
        # Allow overrides in tests while still defaulting to settings.
        self.base_url = base_url if base_url is not None else settings.EKASA_BASE_URL
        self.api_key = api_key if api_key is not None else settings.EKASA_API_KEY
        self.timeout_s = timeout_s if timeout_s is not None else settings.EKASA_TIMEOUT_S

    def _ensure_configured(self) -> None:
        # Fail fast so we never silently "pretend" we called a real device.
        if not self.base_url:
            raise RuntimeError("Ekasa provider is not configured. Set EKASA_BASE_URL.")

    def authorize(self, *, payment, timeout_s: int):
        self._ensure_configured()
        raise NotImplementedError("Ekasa authorize is not implemented yet.")

    def capture(self, *, payment, timeout_s: int):
        self._ensure_configured()
        raise NotImplementedError("Ekasa capture is not implemented yet.")

    def refund(self, *, payment, timeout_s: int):
        self._ensure_configured()
        raise NotImplementedError("Ekasa refund is not implemented yet.")

    def capture_status(self, *, payment, timeout_s: int):
        """
        Optional reconciliation hook for offline capture workflows.
        """
        self._ensure_configured()
        raise NotImplementedError("Ekasa capture status is not implemented yet.")
