import json
import urllib.request

import pytest

from apps.payments.ekasa.client import EkasaClient


class DummyResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_ekasa_client_posts_json(monkeypatch, settings):
    settings.EKASA_BASE_URL = "http://localhost:3010"
    settings.EKASA_API_KEY = "test-api-key"

    captured = {}

    def fake_urlopen(request: urllib.request.Request, timeout: int):
        captured["url"] = request.full_url
        captured["data"] = request.data.decode("utf-8")
        captured["headers"] = dict(request.headers)
        return DummyResponse('{"ok": true}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    client = EkasaClient()
    response = client.register_cash_register(payload={"request": {"data": {"foo": "bar"}}})

    assert response["ok"] is True
    assert captured["url"].endswith("/api/v1/requests/receipts/cash_register")
    assert json.loads(captured["data"])["request"]["data"]["foo"] == "bar"
    assert (captured["headers"].get("Content-Type") or captured["headers"].get("Content-type")) == "application/json"
    assert captured["headers"]["X-api-key"] == "test-api-key"
