import pytest

from apps.payments.ekasa.mapper import extract_receipt_reference


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"receipt_id": "r1"}, "r1"),
        ({"okp": "OKP-1"}, "OKP-1"),
        ({"data": {"receipt_id": "r2"}}, "r2"),
        ({"data": {"okp": "OKP-2"}}, "OKP-2"),
        ({"data": {"receiptId": "r3"}}, "r3"),
        ({"response": {"OKP": "OKP-3"}}, "OKP-3"),
    ],
)
def test_extract_receipt_reference(payload, expected):
    assert extract_receipt_reference(payload) == expected


def test_extract_receipt_reference_returns_none_for_unknown_shape():
    assert extract_receipt_reference({"foo": "bar"}) is None
