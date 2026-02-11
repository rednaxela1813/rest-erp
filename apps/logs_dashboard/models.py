from django.db import models


class LogEntry(models.Model):
    level = models.CharField(max_length=16)
    logger_name = models.CharField(max_length=128, blank=True, default="")
    event = models.CharField(max_length=128, blank=True, default="")
    message = models.TextField(blank=True, default="")

    request_id = models.CharField(max_length=64, blank=True, default="")
    org_id = models.CharField(max_length=64, blank=True, default="")
    user_id = models.CharField(max_length=64, blank=True, default="")
    path = models.CharField(max_length=255, blank=True, default="")
    method = models.CharField(max_length=16, blank=True, default="")

    task_id = models.CharField(max_length=64, blank=True, default="")
    task_name = models.CharField(max_length=255, blank=True, default="")

    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["org_id", "created_at"]),
            models.Index(fields=["level", "created_at"]),
            models.Index(fields=["request_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.level} {self.event or self.message[:40]}"
