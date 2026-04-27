from __future__ import annotations

from django.conf import settings
from rest_framework.exceptions import ValidationError

from apps.orders.logic.refund_order import refund_paid_order
from apps.payments.logic.enqueue_device_commands import _build_fiscal_items, enqueue_payment_commands
from apps.payments import tasks as payment_tasks
from apps.payments.models import CashDrawerMovement, CashierSession, DeviceCommand, OrderPayment

from .cart import SESSION_REFUND_ERROR
from .payment_confirm import trigger_ekasa_processing


FISCAL_COMMAND_TYPES = [
    DeviceCommand.Type.FISCALIZE_SALE,
    DeviceCommand.Type.FISCALIZE_REFUND,
    DeviceCommand.Type.FISCALIZE_STORNO,
]


def build_payment_status_context(*, payment: OrderPayment, logger) -> dict:
    if (
        settings.EKASA_ENABLED
        and payment.status == OrderPayment.Status.CAPTURED
        and payment.fiscal_status == OrderPayment.FiscalStatus.PENDING
    ):
        recreated_missing_command = False
        if not DeviceCommand.objects.filter(payment=payment, command_type__in=FISCAL_COMMAND_TYPES).exists():
            include_kot = payment.order.kitchen_tickets.exists()
            enqueue_payment_commands(payment=payment, include_kot=include_kot, include_payment_capture=False)
            recreated_missing_command = True

        if not recreated_missing_command:
            try:
                payment_tasks.process_device_commands_ekasa.run(org_id=payment.org_id, limit=50)
            except Exception as exc:
                logger.exception(
                    "cashier_payment_status_inline_fiscal_failed",
                    org_id=str(payment.org.public_id),
                    payment_id=str(payment.public_id),
                    error=str(exc),
                )
                payment.fiscal_status = OrderPayment.FiscalStatus.FAILED
                payment.failure_reason = str(exc)
                payment.save(update_fields=["fiscal_status", "failure_reason", "updated_at"])
        payment.refresh_from_db()

    failed_fiscal_command = (
        DeviceCommand.objects.filter(
            payment=payment,
            command_type__in=FISCAL_COMMAND_TYPES,
            status=DeviceCommand.Status.FAILED,
        )
        .order_by("-updated_at", "-created_at")
        .first()
    )
    return {
        "payment": payment,
        "order": payment.order,
        "currency": settings.DEFAULT_CURRENCY,
        "ekasa_enabled": settings.EKASA_ENABLED,
        "fiscal_last_error": failed_fiscal_command.last_error if failed_fiscal_command else "",
        "can_retry_fiscal": (
            settings.EKASA_ENABLED
            and payment.status == OrderPayment.Status.CAPTURED
            and failed_fiscal_command is not None
        ),
    }


def retry_fiscalization(*, payment: OrderPayment, logger) -> None:
    logger.info(
        "cashier_payment_retry_fiscal_started",
        org_id=str(payment.org.public_id),
        payment_id=str(payment.public_id),
    )

    sale_command = (
        DeviceCommand.objects.filter(payment=payment, command_type=DeviceCommand.Type.FISCALIZE_SALE)
        .order_by("-created_at")
        .first()
    )
    if sale_command is None:
        include_kot = payment.order.kitchen_tickets.exists()
        enqueue_payment_commands(payment=payment, include_kot=include_kot, include_payment_capture=False)
        sale_command = (
            DeviceCommand.objects.filter(payment=payment, command_type=DeviceCommand.Type.FISCALIZE_SALE)
            .order_by("-created_at")
            .first()
        )

    if sale_command is not None:
        sale_command.payload = {
            "order_id": str(payment.order.public_id),
            "payment_id": str(payment.public_id),
            "amount": str(payment.amount),
            "currency": payment.currency,
            "tender": payment.tender,
            "items": _build_fiscal_items(payment=payment),
        }
        sale_command.status = DeviceCommand.Status.PENDING
        sale_command.retries = 0
        sale_command.last_error = ""
        sale_command.next_attempt_at = None
        sale_command.save(update_fields=["payload", "status", "retries", "last_error", "next_attempt_at", "updated_at"])

    payment.fiscal_status = OrderPayment.FiscalStatus.PENDING
    payment.failure_reason = ""
    payment.save(update_fields=["fiscal_status", "failure_reason", "updated_at"])
    trigger_ekasa_processing(payment.org_id)
    logger.info(
        "cashier_payment_retry_fiscal_succeeded",
        org_id=str(payment.org.public_id),
        payment_id=str(payment.public_id),
        sale_command_id=str(sale_command.public_id) if sale_command else "",
    )


def refund_order_from_cashier(*, request, order, session: CashierSession, logger) -> None:
    logger.info(
        "cashier_order_refund_started",
        org_id=str(session.org.public_id),
        order_id=str(order.public_id),
        user_id=str(request.user.id),
    )

    try:
        refund_paid_order(order=order, actor=request.user)

        payment = order.payments.filter(status=OrderPayment.Status.CAPTURED).first()
        if payment and payment.tender == OrderPayment.Tender.CASH:
            CashDrawerMovement.objects.create(
                session=session,
                actor=request.user,
                movement_type=CashDrawerMovement.Type.CASH_OUT,
                amount=payment.amount,
                reason=f"Refund: order {order.public_id}",
            )
        trigger_ekasa_processing(session.org_id)
        logger.info(
            "cashier_order_refund_succeeded",
            org_id=str(session.org.public_id),
            order_id=str(order.public_id),
            tender=payment.tender if payment else "",
        )
    except ValidationError as exc:
        logger.warning(
            "cashier_order_refund_failed",
            org_id=str(session.org.public_id),
            order_id=str(order.public_id),
            error=str(exc),
        )
        request.session[SESSION_REFUND_ERROR] = str(exc)
