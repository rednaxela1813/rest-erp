from django.contrib import admin

from .models import KitchenTicket, Order, OrderItem, OrderStatusEvent


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    autocomplete_fields = ("product", "unit", "tax_rate")
    readonly_fields = ("created_at",)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("public_id", "org", "status", "subtotal", "tax_total", "total")
    list_filter = ("status", "org")
    search_fields = ("public_id", "org__name")
    inlines = [OrderItemInline]
    readonly_fields = ("subtotal", "tax_total", "total")


@admin.register(OrderStatusEvent)
class OrderStatusEventAdmin(admin.ModelAdmin):
    list_display = ("order", "from_status", "to_status", "actor", "created_at")
    list_filter = ("from_status", "to_status")
    search_fields = ("order__public_id", "actor__email")


@admin.register(KitchenTicket)
class KitchenTicketAdmin(admin.ModelAdmin):
    list_display = ("order", "product", "qty", "status", "org", "created_at")
    list_filter = ("status", "org")
    search_fields = ("order__public_id", "product__name")
