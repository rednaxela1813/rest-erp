import pytest

from apps.payments.ekasa.mapper import extract_receipt_reference, extract_okp

# Real NineDigit API response (confirmed from Swagger + live response sample)
REAL_RESPONSE = {
    "request": {
        "data": {
            "receiptType": "CashRegister",
            "amount": 2.58,
            "okp": "04eacca4-6ff07dea-c2c85513-28181bb6-f46edcb0",
            "pkp": "GYTIYJs5LL1uY...",
            "cashRegisterCode": "88812345678900001",
        },
        "id": "00000000-0000-0000-0000-000000000000",
        "externalId": None,
        "date": "2026-04-11T15:16:36+02:00",
        "sendingCount": 1,
    },
    "response": {
        "data": {
            "id": "O-7DBCDA8A56EE426DBCDA8A56EE426D1A",
        },
        "processDate": "2026-04-11T15:16:36+02:00",
    },
    "isSuccessful": True,
    "error": None,
    "$type": "Receipt",
}


class TestExtractReceiptReference:
    def test_extracts_response_data_id_from_real_response(self):
        assert extract_receipt_reference(REAL_RESPONSE) == "O-7DBCDA8A56EE426DBCDA8A56EE426D1A"

    def test_returns_none_when_response_data_missing(self):
        assert extract_receipt_reference({"response": {}}) is None

    def test_returns_none_when_response_missing(self):
        assert extract_receipt_reference({"isSuccessful": True}) is None

    def test_returns_none_for_empty_dict(self):
        assert extract_receipt_reference({}) is None

    def test_returns_none_for_none(self):
        assert extract_receipt_reference(None) is None

    def test_returns_none_when_id_is_none(self):
        response = {"response": {"data": {"id": None}}}
        assert extract_receipt_reference(response) is None

    def test_returns_none_when_id_is_empty_string(self):
        response = {"response": {"data": {"id": ""}}}
        assert extract_receipt_reference(response) is None

    def test_returns_string_even_for_numeric_id(self):
        response = {"response": {"data": {"id": 12345}}}
        assert extract_receipt_reference(response) == "12345"


class TestExtractOkp:
    def test_extracts_okp_from_real_response(self):
        assert extract_okp(REAL_RESPONSE) == "04eacca4-6ff07dea-c2c85513-28181bb6-f46edcb0"

    def test_returns_none_when_request_data_missing(self):
        assert extract_okp({"request": {}}) is None

    def test_returns_none_when_request_missing(self):
        assert extract_okp({"isSuccessful": True}) is None

    def test_returns_none_for_empty_dict(self):
        assert extract_okp({}) is None

    def test_returns_none_for_none(self):
        assert extract_okp(None) is None

    def test_returns_none_when_okp_is_none(self):
        response = {"request": {"data": {"okp": None}}}
        assert extract_okp(response) is None
