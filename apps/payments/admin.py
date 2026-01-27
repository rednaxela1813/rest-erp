from django.contrib import admin

from .models import (
    CashierSession,
    CashDrawerMovement,
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
    list_display = ("public_id", "order", "tender", "status", "amount", "currency", "provider")
    list_filter = ("status", "tender", "provider")
    search_fields = ("public_id", "order__public_id")
    readonly_fields = (
        "authorized_at",
        "captured_at",
        "cancelled_at",
    )


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
