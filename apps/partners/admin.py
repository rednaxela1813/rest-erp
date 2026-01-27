from django.contrib import admin

from .models import Partner


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ("name", "org", "status")
    search_fields = ("name", "org__name")
    list_filter = ("status",)
