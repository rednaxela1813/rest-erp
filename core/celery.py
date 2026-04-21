import os

from celery import Celery
import config.observability.celery  # noqa: F401


# Configure Celery to use development settings by default.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.dev")

app = Celery("core")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
