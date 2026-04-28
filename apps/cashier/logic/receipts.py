from __future__ import annotations

from apps.payments.models import CashierSession, OrderPayment

from ..integrations import send_fiscal_receipt, send_receipt_to_printer


def send_receipts(*, order, payment: OrderPayment, session: CashierSession) -> None:
    send_receipt_to_printer(order=order, payment=payment, session=session)
    send_fiscal_receipt(order=order, payment=payment, session=session)
