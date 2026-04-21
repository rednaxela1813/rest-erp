from types import SimpleNamespace

import pytest

from apps.payments.ekasa.mapper import build_cash_register_request
from apps.payments.models import DeviceCommand


def _make_command(*, command_type, payload):
    return SimpleNamespace(command_type=command_type, payload=payload, public_id="cmd-1")


def test_build_cash_register_request_sale():
    command = _make_command(
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        payload={
            "tender": "cash",
            "items": [
                {
                    "name": "Burger",
                    "qty": "2.000",
                    "unit_price": "5.00",
                    "tax_rate": "20.00",
                    "unit": "pcs",
                }
            ],
        },
    )

    data = build_cash_register_request(command=command, cash_register_code="KASA-1")
    req = data["request"]["data"]

    assert req["cashRegisterCode"] == "KASA-1"
    assert req["receiptType"] == "CashRegister"
    assert data["request"]["externalId"] == "cmd-1"

    item = req["items"][0]
    # NineDigit expects PascalCase item types
    assert item["type"] == "Positive"
    assert str(item["unitPrice"]) == "5.00"
    assert str(item["price"]) == "10.00"
    # NineDigit expects quantity as object, not plain number
    assert item["quantity"] == {"amount": pytest.approx(2.0), "unit": "pcs"}

    payment = req["payments"][0]
    # NineDigit payments have no "type" field
    assert "type" not in payment
    assert payment["name"] == "Hotovosť"


def test_build_cash_register_request_card_payment_name():
    command = _make_command(
        command_type=DeviceCommand.Type.FISCALIZE_SALE,
        payload={
            "tender": "card",
            "items": [
                {
                    "name": "Burger",
                    "qty": "1.000",
                    "unit_price": "5.00",
                    "tax_rate": "20.00",
                    "unit": "pcs",
                }
            ],
        },
    )

    data = build_cash_register_request(command=command, cash_register_code="KASA-1")
    payment = data["request"]["data"]["payments"][0]
    assert "type" not in payment
    assert payment["name"] == "Karta"


def test_build_cash_register_request_refund_requires_reference():
    command = _make_command(
        command_type=DeviceCommand.Type.FISCALIZE_REFUND,
        payload={
            "items": [
                {
                    "name": "Burger",
                    "qty": "1.000",
                    "unit_price": "5.00",
                    "tax_rate": "20.00",
                    "unit": "pcs",
                }
            ]
        },
    )

    with pytest.raises(ValueError, match="receipt_id"):
        build_cash_register_request(command=command, cash_register_code="KASA-1")


def test_build_cash_register_request_refund_negative_amounts():
    command = _make_command(
        command_type=DeviceCommand.Type.FISCALIZE_REFUND,
        payload={
            "receipt_id": "ekasa-123",
            "items": [
                {
                    "name": "Burger",
                    "qty": "1.000",
                    "unit_price": "5.00",
                    "tax_rate": "20.00",
                    "unit": "pcs",
                }
            ],
        },
    )

    data = build_cash_register_request(command=command, cash_register_code="KASA-1")
    req = data["request"]["data"]
    assert req["referenceReceiptId"] == "ekasa-123"
    assert req["items"][0]["type"] == "Returned"
    assert str(req["items"][0]["unitPrice"]) == "-5.00"
    assert str(req["items"][0]["price"]) == "-5.00"


def test_build_cash_register_request_storno_negative_amounts():
    command = _make_command(
        command_type=DeviceCommand.Type.FISCALIZE_STORNO,
        payload={
            "receipt_id": "ekasa-456",
            "items": [
                {
                    "name": "Burger",
                    "qty": "1.000",
                    "unit_price": "5.00",
                    "tax_rate": "20.00",
                    "unit": "pcs",
                }
            ],
        },
    )

    data = build_cash_register_request(command=command, cash_register_code="KASA-1")
    req = data["request"]["data"]
    assert req["referenceReceiptId"] == "ekasa-456"
    assert req["items"][0]["type"] == "Correction"
    assert str(req["items"][0]["unitPrice"]) == "-5.00"
