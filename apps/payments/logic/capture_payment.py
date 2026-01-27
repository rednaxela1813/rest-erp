from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.payments.models import FiscalReceipt, OrderPayment
from apps.payments.providers import registry
from apps.orders.logic.finalize_paid_order import finalize_paid_order


def capture_payment(*, payment: OrderPayment, actor=None, timeout_s: int = 30) -> OrderPayment:
    if payment.status != OrderPayment.Status.AUTHORIZED:
        raise ValidationError({"status": ["Payment is not authorized."]})

    provider = registry.get_provider_for_payment(payment)
    payload = provider.capture(payment=payment, timeout_s=timeout_s)

    with transaction.atomic():
        payment.status = OrderPayment.Status.CAPTURED
        payment.captured_at = timezone.now()
        payment.raw_provider_payload = payload
        payment.save(update_fields=["status", "captured_at", "raw_provider_payload", "updated_at"])

        finalize_paid_order(order=payment.order, actor=actor)

        if payment.tender == OrderPayment.Tender.CARD:
            FiscalReceipt.objects.get_or_create(
                payment=payment,
                defaults={
                    "org": payment.org,
                    "order": payment.order,
                    "receipt_type": FiscalReceipt.Type.SALE,
                    "total": payment.amount,
                    "tax_total": payment.order.tax_total,
                    "currency": payment.currency,
                    "raw_payload": payment.raw_provider_payload,
                },
            )

    return payment
