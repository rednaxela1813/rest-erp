from __future__ import annotations

from apps.accounting.logic.record_sale import record_sale
from apps.orders.logic.finalize_paid_order import finalize_paid_order
from apps.payments import tasks as payment_tasks
from apps.payments.logic.enqueue_device_commands import enqueue_payment_commands
from apps.payments.models import FiscalReceipt, OrderPayment


def handle_captured_payment(*, payment: OrderPayment, actor, requires_post_fiscal_finalization: bool) -> None:
    if not requires_post_fiscal_finalization:
        finalize_paid_order(order=payment.order, actor=actor)
        record_sale(order=payment.order, tender=payment.tender)

    if payment.tender == OrderPayment.Tender.CARD and not requires_post_fiscal_finalization:
        create_sale_fiscal_receipt(payment=payment)

    include_kot = payment.order.kitchen_tickets.exists()
    enqueue_payment_commands(payment=payment, include_kot=include_kot)
    if requires_post_fiscal_finalization:
        payment_tasks.process_device_commands_ekasa.delay(org_id=payment.org_id, limit=50)


def create_sale_fiscal_receipt(*, payment: OrderPayment) -> FiscalReceipt:
    receipt, _created = FiscalReceipt.objects.get_or_create(
        payment=payment,
        receipt_type=FiscalReceipt.Type.SALE,
        defaults={
            "org": payment.org,
            "order": payment.order,
            "total": payment.amount,
            "tax_total": payment.order.tax_total,
            "currency": payment.currency,
            "raw_payload": payment.raw_provider_payload,
        },
    )
    return receipt
