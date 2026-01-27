from __future__ import annotations


class BasePaymentProvider:
    def authorize(self, *, payment, timeout_s: int):
        raise NotImplementedError

    def capture(self, *, payment, timeout_s: int):
        raise NotImplementedError

    def refund(self, *, payment, timeout_s: int):
        raise NotImplementedError
