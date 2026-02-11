from django.contrib import admin

from apps.logs_dashboard.models import LogEntry


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "level", "event", "message", "org_id", "request_id")
    list_filter = ("level",)
    search_fields = ("event", "message", "request_id", "org_id")
