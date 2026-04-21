"""
Integration test: real HTTP call to NineDigit eKasa on localhost:3010.

Skipped by default. Run explicitly:
    pytest tests/test_ekasa_integration.py -v -m integration

Requires NineDigit running locally and EKASA_CASH_REGISTER_CODE set in .env.
"""

import json
import os
import re
import pytest
from decimal import Decimal
from unittest.mock import MagicMock

from apps.payments.ekasa.client import EkasaClient
from apps.payments.ekasa.mapper import (
    build_cash_register_request,
    extract_receipt_reference,
    extract_okp,
)
from apps.payments.models import DeviceCommand


def _has_real_cash_register_code(value: str) -> bool:
    if not value:
        return False
    return re.fullmatch(r"\d{17}", value) is not None


def _make_mock_command(command_type=DeviceCommand.Type.FISCALIZE_SALE):
    """Build a minimal mock DeviceCommand for mapper tests."""
    command = MagicMock()
    command.command_type = command_type
    command.public_id = "test-integration-001"
    command.payload = {
        "order_id": "test-order-001",
        "payment_id": "test-payment-001",
        "amount": "2.58",
        "currency": "EUR",
        "tender": "cash",
        "items": [
            {
                "name": "Burger Original",
                "qty": "1",
                "unit_price": "7.00",
                "tax_rate": "23.00",
                "unit": "ks",
            }
        ],
    }
    return command


@pytest.mark.integration
def test_register_cash_register_real_call(settings):
    """
    Makes a real POST /api/v1/requests/receipts/cash_register to NineDigit
    running on localhost:3010 and verifies the response structure.

    What we check:
    - HTTP call succeeds (no exception)
    - isSuccessful is True
    - extract_receipt_reference returns a non-empty string
    - extract_okp returns a non-empty string
    """
    cash_register_code = settings.EKASA_CASH_REGISTER_CODE
    if not _has_real_cash_register_code(cash_register_code):
        pytest.skip("EKASA_CASH_REGISTER_CODE must be set to a real 17-digit code for integration tests")

    command = _make_mock_command()
    payload = build_cash_register_request(
        command=command,
        cash_register_code=cash_register_code,
    )

    base_url = os.environ.get("EKASA_INTEGRATION_BASE_URL", "http://host.docker.internal:3010")
    settings.EKASA_BASE_URL = base_url

    client = EkasaClient(base_url=settings.EKASA_BASE_URL, api_key="", timeout_s=10)
    response = client.register_cash_register(payload=payload)

    # Log full response for debugging
    print("\n--- NineDigit raw response ---")
    print(json.dumps(response, indent=2, default=str))
    print("-----------------------------\n")

    assert response.get("isSuccessful") is True, (
        f"Expected isSuccessful=True, got: {response.get('isSuccessful')}\nerror: {response.get('error')}"
    )

    receipt_id = extract_receipt_reference(response)
    assert receipt_id, f"extract_receipt_reference returned empty. Full response:\n{response}"

    okp = extract_okp(response)
    assert okp, f"extract_okp returned empty. Full response:\n{response}"

    print(f"✅ receipt_id: {receipt_id}")
    print(f"✅ okp: {okp}")


@pytest.mark.integration
def test_register_cash_register_payload_structure(settings):
    """
    Verifies that build_cash_register_request generates the correct
    structure expected by NineDigit API (without making HTTP call).
    """
    command = _make_mock_command()
    result = build_cash_register_request(
        command=command,
        cash_register_code="88812345678900001",
    )

    data = result["request"]["data"]

    assert data["receiptType"] == "CashRegister"
    assert data["cashRegisterCode"] == "88812345678900001"
    assert result["request"]["externalId"] == "test-integration-001"

    item = data["items"][0]
    assert item["type"] == "Positive"
    assert isinstance(item["quantity"], dict), "quantity must be object, not plain number"
    assert "amount" in item["quantity"]
    assert "unit" in item["quantity"]
    assert item["quantity"]["unit"] == "ks"

    payment = data["payments"][0]
    assert "type" not in payment, "NineDigit payments must NOT have 'type' field"
    assert payment["name"] == "Hotovosť"
    assert "amount" in payment
