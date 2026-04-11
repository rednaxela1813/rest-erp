from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from apps.payments.models import DeviceCommand


def _quantize(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _compute_vat_amount(*, gross: Decimal, vat_rate: Decimal) -> Decimal:
    """
    Extract VAT from VAT-inclusive prices (project totals are VAT-inclusive).
    """
    if vat_rate <= 0:
        return Decimal("0.00")
    divisor = Decimal("1.00") + (vat_rate / Decimal("100"))
    return _quantize(gross - (gross / divisor), "0.01")


# NineDigit item types are PascalCase (confirmed from Swagger sample)
_ITEM_TYPE_MAP = {
    "positive":   "Positive",
    "returned":   "Returned",
    "correction": "Correction",
}


def build_cash_register_request(*, command, cash_register_code: str) -> dict:
    """
    Build the cash-register receipt payload for NineDigit eKasa Web API.

    Item structure confirmed from NineDigit Swagger:
    - quantity is an object {"amount": ..., "unit": ...}, not a plain number
    - item type is PascalCase: "Positive", "Returned", "Correction"
    - payments have only "name" and "amount" — no "type" field

    For refund/storno: item type is "Returned"/"Correction", amounts are negative.
    """
    payload = command.payload or {}
    items_payload = payload.get("items") or []
    if not items_payload:
        raise ValueError("Command payload is missing items.")

    if not cash_register_code:
        raise ValueError("EKASA_CASH_REGISTER_CODE is required.")

    if command.command_type == DeviceCommand.Type.FISCALIZE_REFUND:
        item_type = "returned"
        amount_sign = Decimal("-1")
        reference_receipt_id = payload.get("receipt_id")
    elif command.command_type == DeviceCommand.Type.FISCALIZE_STORNO:
        item_type = "correction"
        amount_sign = Decimal("-1")
        reference_receipt_id = payload.get("receipt_id")
    else:
        item_type = "positive"
        amount_sign = Decimal("1")
        reference_receipt_id = None

    if item_type in {"returned", "correction"} and not reference_receipt_id:
        raise ValueError("Refund/storno requires receipt_id in payload.")

    items = []
    total = Decimal("0.00")
    for item in items_payload:
        qty = Decimal(str(item.get("qty", "0")))
        unit_price = Decimal(str(item.get("unit_price", "0.00"))) * amount_sign
        vat_rate = Decimal(str(item.get("tax_rate", "0.00")))
        gross = _quantize(qty * unit_price, "0.01")

        items.append(
            {
                "name": item.get("name", ""),
                "type": _ITEM_TYPE_MAP[item_type],
                # NineDigit expects quantity as object, not a plain number
                "quantity": {
                    "amount": _quantize(qty, "0.0000"),
                    "unit": item.get("unit", "x"),
                },
                "unitPrice": _quantize(unit_price, "0.01"),
                "price": gross,
                "vatRate": _quantize(vat_rate, "0.00"),
            }
        )
        total += gross

    tender = str(payload.get("tender") or "card").lower()
    # NineDigit payments: only "name" and "amount", no "type" field
    payments = [
        {
            "name": "Hotovosť" if tender == "cash" else "Karta",
            "amount": _quantize(total, "0.01"),
        }
    ]

    data = {
        "cashRegisterCode": cash_register_code,
        "receiptType": "CashRegister",
        "items": items,
        "payments": payments,
    }
    if reference_receipt_id:
        data["referenceReceiptId"] = reference_receipt_id

    return {"request": {"data": data, "externalId": str(command.public_id)}}


def extract_receipt_reference(response: dict) -> str | None:
    """
    Extract eKasa receipt ID from NineDigit API response.

    Real response schema (confirmed from NineDigit Swagger):
    {
      "response": {
        "data": {
          "id": "O-7DBCDA8A56EE426DBCDA8A56EE426D1A"
        },
        "processDate": "..."
      },
      "isSuccessful": true,
    }

    Returns response.data.id — used as receipt_id for future refund/storno.
    """
    if not isinstance(response, dict):
        return None
    try:
        receipt_id = response["response"]["data"]["id"]
        return str(receipt_id) if receipt_id else None
    except (KeyError, TypeError):
        return None


def extract_okp(response: dict) -> str | None:
    """
    Extract OKP (Overovací Kód Pokladnice) from NineDigit API response.

    OKP is stored in request.data.okp in the response echo — it appears
    on the printed receipt and is required for fiscal verification.

    Real response schema:
    {
      "request": {
        "data": {
          "okp": "04eacca4-6ff07dea-c2c85513-28181bb6-f46edcb0",
        }
      }
    }
    """
    if not isinstance(response, dict):
        return None
    try:
        okp = response["request"]["data"]["okp"]
        return str(okp) if okp else None
    except (KeyError, TypeError):
        return None
