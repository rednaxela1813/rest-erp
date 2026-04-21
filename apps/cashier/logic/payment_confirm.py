"""
Payment confirmation use-cases for the cashier UI.

_confirm_cash_payment и _confirm_card_payment — это UI-специфичные оркестраторы
поверх payments/logic/. Они живут здесь, а не в payments/, потому что знают
о CashDrawerMovement, CashierSession и receipt-sending — вещах специфичных для
кассового экрана.
"""

from __future__ import annotations

import structlog
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounting.logic.record_sale import record_sale
from apps.orders.logic.finalize_paid_order import finalize_paid_order
from apps.payments.logic.authorize_payment import authorize_payment
from apps.payments.logic.capture_payment import capture_payment
from apps.payments.logic.enqueue_device_commands import enqueue_payment_commands
from apps.payments.models import CashDrawerMovement, CashierSession, OrderPayment

from ..integrations import send_fiscal_receipt, send_receipt_to_printer

logger = structlog.get_logger(__name__)


def trigger_ekasa_processing(org_id: int) -> None:
    """Запускает обработку очереди eKasa команд если интеграция включена."""
    if not settings.EKASA_ENABLED:
        return
    from apps.payments.tasks import process_device_commands_ekasa

    process_device_commands_ekasa.delay(org_id=org_id, limit=50)


def send_receipts(*, order, payment: OrderPayment, session: CashierSession) -> None:
    send_receipt_to_printer(order=order, payment=payment, session=session)
    send_fiscal_receipt(order=order, payment=payment, session=session)


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

    CashDrawerMovement.objects.create(
        session=session,
        actor=actor,
        movement_type=CashDrawerMovement.Type.SALE_CASH,
        amount=payment.amount,
    )
    include_kot = payment.order.kitchen_tickets.exists()
    enqueue_payment_commands(
        payment=payment,
        include_kot=include_kot,
        include_payment_capture=False,
    )
    trigger_ekasa_processing(payment.org_id)
    send_receipts(order=payment.order, payment=payment, session=session)
    return payment


def confirm_card_payment(*, payment: OrderPayment, actor, session: CashierSession) -> OrderPayment:
    """
    Подтверждает карточную оплату через authorize → capture цепочку.
    Отправляет чек после успешного capture.
    """
    if payment.status == OrderPayment.Status.CAPTURED:
        return payment

    if payment.status == OrderPayment.Status.PENDING:
        try:
            authorize_payment(payment=payment, actor=actor, terminal=session.terminal, session=session)
            payment.refresh_from_db()
        except ValidationError as exc:
            payment.status = OrderPayment.Status.FAILED
            payment.failure_reason = str(exc)
            payment.save(update_fields=["status", "failure_reason", "updated_at"])
            return payment

    if payment.status == OrderPayment.Status.AUTHORIZED:
        try:
            capture_payment(payment=payment, actor=actor)
            payment.refresh_from_db()
        except ValidationError as exc:
            payment.status = OrderPayment.Status.FAILED
            payment.failure_reason = str(exc)
            payment.save(update_fields=["status", "failure_reason", "updated_at"])
            return payment

    send_receipts(order=payment.order, payment=payment, session=session)
    return payment


def create_payment(
    *,
    order,
    session: CashierSession,
    tender: str,
    idempotency_key: str | None = None,
) -> OrderPayment:
    """Создаёт OrderPayment в статусе PENDING."""
    from django.conf import settings

    return OrderPayment.objects.create(
        org=order.org,
        order=order,
        terminal=session.terminal,
        tender=tender,
        status=OrderPayment.Status.PENDING,
        amount=order.total,
        currency=settings.DEFAULT_CURRENCY,
        provider="manual",
        idempotency_key=idempotency_key,
    )
