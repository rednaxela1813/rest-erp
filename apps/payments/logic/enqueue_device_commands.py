from __future__ import annotations

from apps.payments.models import DeviceCommand, OrderPayment


def _build_idempotency_key(*, command_type: str, payment_id: int) -> str:
    """
    Create a deterministic idempotency key for device commands.

    We intentionally avoid randomness here:
    - Same payment + same command type => same key
    - Safe to retry without duplicating commands
    """
    return f"{command_type}:{payment_id}"

def _build_fiscal_items(*, payment: OrderPayment) -> list[dict]:
    """
    Build a stable list of fiscal line items for device commands.

    This keeps local agents (mock or real eKasa) independent of ORM lookups.
    """
    order = payment.order
    items = []

    for item in order.items.select_related("unit", "tax_rate").prefetch_related("addons").all():
        items.append(
            {
                "name": item.product_name,
                "qty": str(item.qty),
                "unit_price": str(item.unit_price),
                "tax_rate": str(item.tax_rate.rate if item.tax_rate else "0.00"),
                "unit": item.unit.name if item.unit else "x",
            }
        )

        # Addons are represented as separate receipt items.
        for addon in item.addons.all():
            items.append(
                {
                    "name": addon.name,
                    "qty": str(addon.qty),
                    "unit_price": str(addon.price),
                    "tax_rate": str(item.tax_rate.rate if item.tax_rate else "0.00"),
                    "unit": item.unit.name if item.unit else "x",
                }
            )

    return items


def enqueue_payment_commands(
    *,
    payment: OrderPayment,
    include_kot: bool,
    include_payment_capture: bool = True,
) -> None:
    """
    Enqueue device commands for the Local Agent.

    The server never talks to USB/COM directly. Instead it:
    1) Writes commands to the outbox
    2) Local Agent pulls them, executes, then ACK/FAILs
    """
    command_specs = [
        DeviceCommand.Type.FISCALIZE_SALE,
        DeviceCommand.Type.PRINT_RECEIPT,
    ]
    if include_payment_capture:
        command_specs.insert(0, DeviceCommand.Type.PAYMENT_CAPTURE)

    if include_kot:
        command_specs.append(DeviceCommand.Type.PRINT_KOT)

    # We use get_or_create to guarantee idempotency at the DB level.
    for command_type in command_specs:
        DeviceCommand.objects.get_or_create(
            org=payment.org,
            idempotency_key=_build_idempotency_key(
                command_type=command_type, payment_id=payment.id
            ),
            defaults={
                "order": payment.order,
                "payment": payment,
                "command_type": command_type,
                "payload": {
                    "order_id": str(payment.order.public_id),
                    "payment_id": str(payment.public_id),
                    "amount": str(payment.amount),
                    "currency": payment.currency,
                    "tender": payment.tender,
                    "items": _build_fiscal_items(payment=payment),
                },
            },
        )


def enqueue_refund_commands(*, payment: OrderPayment, receipt_public_id: str) -> None:
    """
    Enqueue refund-related commands for Local Agent.

    We keep the command set minimal:
    - fiscalize_refund (eKasa refund/storno)
    - print_receipt (refund receipt)
    """
    command_specs = [
        DeviceCommand.Type.FISCALIZE_REFUND,
        DeviceCommand.Type.PRINT_RECEIPT,
    ]

    for command_type in command_specs:
        DeviceCommand.objects.get_or_create(
            org=payment.org,
            idempotency_key=_build_idempotency_key(
                command_type=command_type, payment_id=payment.id
            ),
            defaults={
                "order": payment.order,
                "payment": payment,
                "command_type": command_type,
                "payload": {
                    "order_id": str(payment.order.public_id),
                    "payment_id": str(payment.public_id),
                    "receipt_id": receipt_public_id,
                    "amount": str(payment.amount),
                    "currency": payment.currency,
                    "tender": payment.tender,
                    "items": _build_fiscal_items(payment=payment),
                },
            },
        )


def enqueue_storno_commands(*, payment: OrderPayment, receipt_public_id: str) -> None:
    """
    Enqueue storno-related commands for Local Agent.

    Command set is explicit to keep fiscal workflow traceable:
    - fiscalize_storno
    - print_receipt
    """
    command_specs = [
        DeviceCommand.Type.FISCALIZE_STORNO,
        DeviceCommand.Type.PRINT_RECEIPT,
    ]

    for command_type in command_specs:
        DeviceCommand.objects.get_or_create(
            org=payment.org,
            idempotency_key=_build_idempotency_key(
                command_type=command_type, payment_id=payment.id
            ),
            defaults={
                "order": payment.order,
                "payment": payment,
                "command_type": command_type,
                "payload": {
                    "order_id": str(payment.order.public_id),
                    "payment_id": str(payment.public_id),
                    "receipt_id": receipt_public_id,
                    "amount": str(payment.amount),
                    "currency": payment.currency,
                    "tender": payment.tender,
                    "items": _build_fiscal_items(payment=payment),
                },
            },
        )
