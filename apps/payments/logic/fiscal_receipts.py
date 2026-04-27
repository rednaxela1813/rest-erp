from __future__ import annotations

from apps.accounting.logic.record_sale import record_sale
from apps.orders.logic.finalize_paid_order import finalize_paid_order
from apps.payments.models import DeviceCommand, FiscalReceipt, OrderPayment


def finalize_sale_after_fiscal_confirmation(*, payment: OrderPayment) -> None:
    order = payment.order
    if order.status != order.STATUS_PAID:
        finalize_paid_order(order=order, actor=None)
        order.refresh_from_db(fields=["status", "updated_at"])
    record_sale(order=order, tender=payment.tender)


def ensure_fiscal_receipt(*, command: DeviceCommand, raw_payload: dict | None = None) -> None:
    if command.command_type == DeviceCommand.Type.FISCALIZE_SALE:
        receipt_type = FiscalReceipt.Type.SALE
    elif command.command_type == DeviceCommand.Type.FISCALIZE_REFUND:
        receipt_type = FiscalReceipt.Type.REFUND
    elif command.command_type == DeviceCommand.Type.FISCALIZE_STORNO:
        receipt_type = FiscalReceipt.Type.STORNO
    else:
        return

    payment = command.payment
    order = command.order
    if not payment:
        return

    FiscalReceipt.objects.get_or_create(
        payment=payment,
        receipt_type=receipt_type,
        defaults={
            "org": payment.org,
            "order": order,
            "total": payment.amount,
            "tax_total": order.tax_total if order else 0,
            "currency": payment.currency,
            "raw_payload": raw_payload or {"mock": True, "command_id": str(command.public_id)},
        },
    )
