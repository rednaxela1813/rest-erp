from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounting.logic.record_sale import record_sale
from apps.orders.logic.finalize_paid_order import finalize_paid_order
from apps.payments.logic.enqueue_device_commands import enqueue_payment_commands
from apps.payments.models import CashierSession, OrderPayment

from .cash_drawer import record_cash_sale
from .ekasa import trigger_ekasa_processing
from .receipts import send_receipts


def confirm_cash_payment(*, payment: OrderPayment, actor, session: CashierSession) -> OrderPayment:
    """
    Подтверждает наличную оплату:
    1. Переводит payment в CAPTURED
    2. Если eKasa выключена — финализирует заказ и списывает остатки
    3. Записывает движение в кассовый ящик
    4. Ставит команды в очередь устройства
    5. Отправляет чек
    """
    if payment.status == OrderPayment.Status.CAPTURED:
        return payment

    payment.status = OrderPayment.Status.CAPTURED
    payment.captured_at = timezone.now()
    if settings.EKASA_ENABLED:
        payment.fiscal_status = OrderPayment.FiscalStatus.PENDING
        payment.save(update_fields=["status", "captured_at", "fiscal_status", "updated_at"])
    else:
        payment.save(update_fields=["status", "captured_at", "updated_at"])

    if not settings.EKASA_ENABLED:
        try:
            finalize_paid_order(order=payment.order, actor=actor)
        except ValidationError as exc:
            payment.status = OrderPayment.Status.FAILED
            payment.failure_reason = str(exc)
            payment.save(update_fields=["status", "failure_reason", "updated_at"])
            return payment
        record_sale(order=payment.order, tender=payment.tender)

    record_cash_sale(payment=payment, session=session, actor=actor)
    include_kot = payment.order.kitchen_tickets.exists()
    enqueue_payment_commands(
        payment=payment,
        include_kot=include_kot,
        include_payment_capture=False,
    )
    trigger_ekasa_processing(payment.org_id)
    send_receipts(order=payment.order, payment=payment, session=session)
    return payment
