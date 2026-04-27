# rest-erp/apps/payments/providers/ekasa.py
from __future__ import annotations

from django.conf import settings
import structlog

from apps.payments.providers.base import BasePaymentProvider

logger = structlog.get_logger(__name__)


class EkasaProvider(BasePaymentProvider):
    """
    NineDigit eKasa Web API provider.

    eKasa is a fiscal device — it does not authorize card payments.
    Authorization/capture happen either via NEXO (card) or at the
    cashier desk (cash).  This provider handles only the fiscal
    registration that happens *after* payment is captured, which is
    driven by the process_device_commands_ekasa Celery task.

    authorize/capture/refund are therefore intentional no-ops here:
    the real work is done asynchronously by the task queue.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_s: int | None = None,
    ) -> None:
        self.base_url = base_url if base_url is not None else settings.EKASA_BASE_URL
        self.api_key = api_key if api_key is not None else settings.EKASA_API_KEY
        self.timeout_s = timeout_s if timeout_s is not None else settings.EKASA_TIMEOUT_S

    def _ensure_configured(self) -> None:
        if not self.base_url:
            raise RuntimeError("eKasa provider is not configured — set EKASA_BASE_URL.")

    # ------------------------------------------------------------------
    # These three are intentional pass-throughs.
    # Fiscal registration is enqueued by capture_payment and processed
    # asynchronously by process_device_commands_ekasa.
    # ------------------------------------------------------------------

    def authorize(self, *, payment, timeout_s: int) -> dict:
        self._ensure_configured()
        logger.info("ekasa_authorize_passthrough", payment_id=str(payment.public_id))
        return {"ok": True, "provider": "ekasa", "action": "authorize"}

    def capture(self, *, payment, timeout_s: int) -> dict:
        self._ensure_configured()
        logger.info("ekasa_capture_passthrough", payment_id=str(payment.public_id))
        return {"ok": True, "provider": "ekasa", "action": "capture"}

    def refund(self, *, payment, timeout_s: int) -> dict:
        self._ensure_configured()
        logger.info("ekasa_refund_passthrough", payment_id=str(payment.public_id))
        return {"ok": True, "provider": "ekasa", "action": "refund"}

    def capture_status(self, *, payment, timeout_s: int) -> dict:
        """
        Reconciliation: derive capture status from fiscal_status,
        since eKasa receipts confirm the payment implicitly.
        """
        from apps.payments.models import OrderPayment

        if payment.fiscal_status == OrderPayment.FiscalStatus.CONFIRMED:
            return {"status": "confirmed"}
        if payment.fiscal_status == OrderPayment.FiscalStatus.FAILED:
            return {"status": "failed"}
        return {"status": "pending"}
