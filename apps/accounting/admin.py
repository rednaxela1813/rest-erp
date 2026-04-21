from django.contrib import admin

from .models import AccountingEntry


@admin.register(AccountingEntry)
class AccountingEntryAdmin(admin.ModelAdmin):
    list_display = ("id", "entry_type", "amount", "currency", "partner", "transaction_date", "export_status")
    list_filter = ("entry_type", "export_status", "transaction_date")
    search_fields = ("partner__name", "note")
