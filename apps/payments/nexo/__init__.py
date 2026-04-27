# rest-erp/apps/payments/nexo/__init__.py
from __future__ import annotations

import base64
import json
import uuid
import urllib.request
import urllib.error
from decimal import Decimal


_DEFAULT_USERNAME = "user"
_DEFAULT_PASSWORD = "pass"
_DEFAULT_TIMEOUT_S = 60  # card transactions can take up to ~60 s


class NexoClient:
    """
    Minimal NEXO 3.1 HTTP client for SUNMI P3H (Besteron).

    Uses stdlib urllib — no extra deps.
    The terminal speaks synchronous HTTP POST on port 7500.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int = 7500,
        sale_id: str,
        poi_id: str,
        username: str = _DEFAULT_USERNAME,
        password: str = _DEFAULT_PASSWORD,
        timeout_s: int = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self.url = f"http://{host}:{port}"
        self.sale_id = sale_id
        self.poi_id = poi_id
        self.timeout_s = timeout_s
        raw = f"{username}:{password}".encode()
        self._auth = base64.b64encode(raw).decode("ascii")

    # ------------------------------------------------------------------
    # Public commands
    # ------------------------------------------------------------------

    def payment(self, *, amount: Decimal, currency: str, tip: Decimal | None = None) -> dict:
        body: dict = {
            "PaymentTransaction": {
                "AmountsReq": {
                    "Currency": currency,
                    "RequestedAmount": float(amount),
                }
            },
            "SaleData": {"SaleTransactionID": self._tx_id()},
        }
        if tip is not None and tip > 0:
            body["PaymentTransaction"]["AmountsReq"]["TipAmount"] = float(tip)
        return self._request("Payment", "PaymentRequest", body)

    def refund(self, *, amount: Decimal, currency: str) -> dict:
        body = {
            "PaymentData": {"PaymentType": "Refund"},
            "PaymentTransaction": {"AmountsReq": {"Currency": currency, "RequestedAmount": float(amount)}},
            "SaleData": {"SaleTransactionID": self._tx_id()},
        }
        return self._request("Payment", "PaymentRequest", body)

    def reversal(self, *, poi_transaction_id: str) -> dict:
        body = {
            "OriginalPOITransaction": {"POITransactionID": {"TransactionID": poi_transaction_id}},
            "ReversalReason": "MerchantCancel",
        }
        return self._request("Reversal", "ReversalRequest", body)

    def transaction_status(self, *, service_id: str) -> dict:
        body = {"MessageReference": {"ServiceID": service_id}}
        return self._request("TransactionStatus", "TransactionStatusRequest", body)

    def diagnosis(self) -> dict:
        return self._request("Diagnosis", "DiagnosisRequest", {"HostDiagnosisFlag": False})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _tx_id(self) -> dict:
        from django.utils import timezone

        return {
            "TimeStamp": timezone.now().isoformat(),
            "TransactionID": str(uuid.uuid4()),
        }

    def _request(self, category: str, request_key: str, body: dict) -> dict:
        service_id = str(uuid.uuid4())
        payload = {
            "SaleToPOIRequest": {
                "MessageHeader": {
                    "MessageCategory": category,
                    "MessageClass": "Service",
                    "MessageType": "Request",
                    "POIID": self.poi_id,
                    "ProtocolVersion": "3.1",
                    "SaleID": self.sale_id,
                    "ServiceID": service_id,
                },
                request_key: body,
            }
        }
        raw = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url=self.url,
            data=raw,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(raw)),
                "Authorization": f"Basic {self._auth}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8") if exc.fp else ""
            raise RuntimeError(f"NEXO HTTP {exc.code}: {detail}") from exc
