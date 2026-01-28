from __future__ import annotations

from apps.payments.providers.base import BasePaymentProvider


class ManualProvider(BasePaymentProvider):
    def authorize(self, *, payment, timeout_s: int):
        return {"ok": True, "provider": "manual", "action": "authorize"}

    def capture(self, *, payment, timeout_s: int):
        return {"ok": True, "provider": "manual", "action": "capture"}

    def refund(self, *, payment, timeout_s: int):
        return {"ok": True, "provider": "manual", "action": "refund"}

    def capture_status(self, *, payment, timeout_s: int):
        """
        Manual provider treats captured payments as confirmed.
        """
        if payment.status == payment.Status.CAPTURED:
            return {"status": "confirmed"}
        if payment.status == payment.Status.FAILED:
            return {"status": "failed"}
        return {"status": "pending"}
