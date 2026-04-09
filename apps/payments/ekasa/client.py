from __future__ import annotations

import base64
import json
import urllib.request
import urllib.error
from decimal import Decimal
from typing import Any

from django.conf import settings


class EkasaClient:
    """
    Minimal HTTP client for NineDigit eKasa Web API.

    Uses stdlib urllib to avoid extra dependencies.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_s: int | None = None,
    ):
        self.base_url = (base_url if base_url is not None else settings.EKASA_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.EKASA_API_KEY
        self.timeout_s = timeout_s if timeout_s is not None else settings.EKASA_TIMEOUT_S

    def register_cash_register(self, *, payload: dict) -> dict[str, Any]:
        """
        Register a cash register receipt via /api/v1/requests/receipts/cash_register.
        """
        if not self.base_url:
            raise RuntimeError("EKASA_BASE_URL is required for eKasa API calls.")

        url = f"{self.base_url}/api/v1/requests/receipts/cash_register"
        return self._post_json(url=url, payload=payload)

    def _post_json(self, *, url: str, payload: dict) -> dict[str, Any]:
        body = json.dumps(payload, default=_json_default).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        # If the local eKasa service requires HTTP Basic auth, set these in env.
        username = settings.EKASA_USERNAME
        password = settings.EKASA_PASSWORD
        if username and password:
            token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"

        request = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8") if exc.fp else ""
            raise RuntimeError(f"eKasa HTTP {exc.code}: {raw}") from exc

        if not raw:
            return {}
        return json.loads(raw)


def _json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")
