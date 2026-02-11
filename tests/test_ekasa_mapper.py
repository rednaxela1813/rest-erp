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
            ]
        },
    )

    data = build_cash_register_request(command=command, cash_register_code="KASA-1")
    req = data["request"]["data"]
    assert req["cashRegisterCode"] == "KASA-1"
    assert req["items"][0]["type"] == "positive"
    assert str(req["items"][0]["unitPrice"]) == "5.00"
    assert str(req["items"][0]["price"]) == "10.00"
    assert req["payments"][0]["type"] == "cash"


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
    assert req["items"][0]["type"] == "returned"
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
    assert req["items"][0]["type"] == "correction"
    assert str(req["items"][0]["unitPrice"]) == "-5.00"
