from django.contrib import admin

from .models import StockLot


@admin.register(StockLot)
class StockLotAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "supplier", "initial_qty", "remaining_qty", "unit_cost", "status", "received_at")
    list_filter = ("status", "product__name", "supplier__name")
    search_fields = ("product__name", "supplier__name", "batch_number")
