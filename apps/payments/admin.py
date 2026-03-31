from django.contrib import admin

from apps.payments.logic.enqueue_device_commands import _build_fiscal_items
from .models import (
    CashierSession,
    CashDrawerMovement,
    DeviceCommand,
    FiscalReceipt,
    OrderPayment,
    PaymentEvent,
    PaymentProviderConfig,
    Terminal,
)


@admin.register(Terminal)
class TerminalAdmin(admin.ModelAdmin):
    list_display = ("name", "org", "code", "status")
    search_fields = ("name", "org__name", "code")
    list_filter = ("status",)


@admin.register(PaymentProviderConfig)
class PaymentProviderConfigAdmin(admin.ModelAdmin):
    list_display = ("provider", "name", "org", "is_active")
    search_fields = ("provider", "name", "org__name")
    list_filter = ("is_active",)


@admin.register(OrderPayment)
class OrderPaymentAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "order",
        "tender",
        "status",
        "capture_status",
        "fiscal_status",
        "amount",
        "currency",
        "provider",
    )
    list_filter = ("status", "tender", "provider")
    search_fields = ("public_id", "order__public_id")
    readonly_fields = (
        "authorized_at",
        "captured_at",
        "cancelled_at",
    )
    actions = (
        "mark_capture_confirmed",
        "mark_capture_timeout",
        "mark_fiscal_confirmed",
        "mark_fiscal_failed",
    )

    def mark_capture_confirmed(self, request, queryset):
        """
        Admin override for confirmed bank capture.
        """
        updated = queryset.update(capture_status=OrderPayment.CaptureStatus.CONFIRMED)
        self.message_user(request, f"Updated capture_status=confirmed for {updated} payments.")

    def mark_capture_timeout(self, request, queryset):
        """
        Admin override for capture timeout after an outage.
        """
        updated = queryset.update(capture_status=OrderPayment.CaptureStatus.TIMEOUT)
        self.message_user(request, f"Updated capture_status=timeout for {updated} payments.")

    def mark_fiscal_confirmed(self, request, queryset):
        """
        Admin override for successful fiscalization.
        """
        updated = queryset.update(fiscal_status=OrderPayment.FiscalStatus.CONFIRMED)
        self.message_user(request, f"Updated fiscal_status=confirmed for {updated} payments.")

    def mark_fiscal_failed(self, request, queryset):
        """
        Admin override for fiscalization failure.
        """
        updated = queryset.update(fiscal_status=OrderPayment.FiscalStatus.FAILED)
        self.message_user(request, f"Updated fiscal_status=failed for {updated} payments.")


@admin.register(DeviceCommand)
class DeviceCommandAdmin(admin.ModelAdmin):
    list_display = ("public_id", "command_type", "status", "retries", "payment", "order", "created_at")
    list_filter = ("command_type", "status")
    search_fields = ("public_id", "payment__public_id", "order__public_id")
    actions = ("requeue_for_retry",)

    def requeue_for_retry(self, request, queryset):
        """
        Manual resolution for eKasa/device errors:
        - Reset retries to allow processing again.
        - Clear next_attempt_at to make it eligible immediately.
        """
        updated = 0
        for command in queryset.select_related("payment", "order"):
            if command.command_type == DeviceCommand.Type.FISCALIZE_SALE and command.payment_id:
                payment = command.payment
                command.payload = {
                    "order_id": str(payment.order.public_id),
                    "payment_id": str(payment.public_id),
                    "amount": str(payment.amount),
                    "currency": payment.currency,
                    "tender": payment.tender,
                    "items": _build_fiscal_items(payment=payment),
                }
            command.status = DeviceCommand.Status.PENDING
            command.retries = 0
            command.last_error = "manual_requeue"
            command.next_attempt_at = None
            command.save(
                update_fields=[
                    "payload",
                    "status",
                    "retries",
                    "last_error",
                    "next_attempt_at",
                    "updated_at",
                ]
            )
            updated += 1
        self.message_user(request, f"Re-queued {updated} device commands for retry.")


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ("payment", "event_type", "actor", "created_at")
    list_filter = ("event_type",)
    search_fields = ("payment__public_id", "actor__email")


@admin.register(CashierSession)
class CashierSessionAdmin(admin.ModelAdmin):
    list_display = ("terminal", "cashier", "org", "status", "opened_at", "closed_at")
    list_filter = ("status",)
    search_fields = ("terminal__name", "cashier__email", "org__name")


@admin.register(CashDrawerMovement)
class CashDrawerMovementAdmin(admin.ModelAdmin):
    list_display = ("session", "movement_type", "amount", "actor", "created_at")
    list_filter = ("movement_type",)
    search_fields = ("session__terminal__name", "actor__email")


@admin.register(FiscalReceipt)
class FiscalReceiptAdmin(admin.ModelAdmin):
    list_display = ("public_id", "receipt_type", "org", "order", "payment", "total", "currency", "created_at")
    list_filter = ("receipt_type", "currency")
    search_fields = ("public_id", "payment__public_id", "order__public_id")
    readonly_fields = ("public_id", "uid", "created_at")
