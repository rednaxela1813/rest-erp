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


def build_cash_register_request(*, command, cash_register_code: str) -> dict:
    """
    Build the cash-register receipt payload for eKasa Web API.

    For refund/storno, we map to 'returned' and 'correction' item types
    and use negative amounts as shown in vendor examples.
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
    total_vat = Decimal("0.00")
    for item in items_payload:
        qty = Decimal(str(item.get("qty", "0")))
        unit_price = Decimal(str(item.get("unit_price", "0.00"))) * amount_sign
        vat_rate = Decimal(str(item.get("tax_rate", "0.00")))
        gross = _quantize(qty * unit_price, "0.01")
        vat_amount = _compute_vat_amount(gross=gross, vat_rate=vat_rate)

        items.append(
            {
                "name": item.get("name", ""),
                "type": item_type,
                "quantity": _quantize(qty, "0.0000"),
                "unit": item.get("unit", "x"),
                "unitPrice": _quantize(unit_price, "0.01"),
                "price": gross,
                "vatRate": _quantize(vat_rate, "0.00"),
                "vatAmount": vat_amount,
            }
        )
        total += gross
        total_vat += vat_amount

    tender = str(payload.get("tender") or "card").lower()
    payment_type = "cash" if tender == "cash" else "card"
    payments = [
        {
            "type": payment_type,
            "amount": _quantize(total, "0.01"),
        }
    ]

    data = {
        "cashRegisterCode": cash_register_code,
        "items": items,
        "payments": payments,
        "externalId": str(command.public_id),
    }
    if reference_receipt_id:
        data["referenceReceiptId"] = reference_receipt_id

    return {"request": {"data": data}}


def extract_receipt_reference(response: dict) -> str | None:
    """
    Extract eKasa receipt reference (receipt_id/OKP) from API response.

    The exact field names depend on the vendor payload. We keep this mapper
    tolerant and expand it once we see the real response schema.
    """
    if not isinstance(response, dict):
        return None

    # Common nested patterns we might see in demo/production payloads.
    candidates = [
        ("receipt_id",),
        ("okp",),
        ("data", "receipt_id"),
        ("data", "okp"),
        ("data", "receiptId"),
        ("data", "OKP"),
        ("response", "receipt_id"),
        ("response", "okp"),
        ("response", "receiptId"),
        ("response", "OKP"),
    ]

    for path in candidates:
        node = response
        for key in path:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if node:
            return str(node)

    return None
