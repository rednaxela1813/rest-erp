from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
import structlog

from apps.payments.models import DeviceCommand

logger = structlog.get_logger(__name__)


_MANUAL_RETRY_ONLY_COMMAND_TYPES = [
    DeviceCommand.Type.FISCALIZE_SALE,
    DeviceCommand.Type.FISCALIZE_REFUND,
    DeviceCommand.Type.FISCALIZE_STORNO,
]


def _compute_retry_delay_seconds(retries: int) -> int:
    """
    Exponential backoff for device command retries with a hard cap.
    """
    base = getattr(settings, "DEVICE_COMMANDS_RETRY_BASE_SECONDS", 10)
    cap = getattr(settings, "DEVICE_COMMANDS_RETRY_MAX_SECONDS", 300)
    delay = base * (2 ** max(retries - 1, 0))
    return min(delay, cap)


def pull_device_commands(*, org, limit: int = 50, command_types: list[str] | None = None) -> list[DeviceCommand]:
    """
    Fetch pending commands and mark them as SENT in one transaction.

    This prevents multiple agents from executing the same command concurrently.
    """
    logger.info(
        "device_commands_pull_started",
        org_id=str(org.public_id),
        limit=limit,
        command_types=command_types or [],
    )
    with transaction.atomic():
        now = timezone.now()
        # Lock only the rows we are going to take, and skip rows locked by other agents.
        commands_qs = (
            DeviceCommand.objects
            .select_for_update(skip_locked=True)
            .filter(
                org=org,
                status=DeviceCommand.Status.PENDING,
                retries__lt=models.F("max_retries"),
            )
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        )
        if command_types:
            commands_qs = commands_qs.filter(command_type__in=command_types)

        commands_qs = commands_qs.order_by("created_at", "id")[:limit]

        # Evaluate queryset inside the transaction to keep locks consistent.
        commands = list(commands_qs)

        # Mark commands as SENT so other agents don't pick them up.
        if commands:
            DeviceCommand.objects.filter(id__in=[cmd.id for cmd in commands]).update(
                status=DeviceCommand.Status.SENT
            )
            for cmd in commands:
                cmd.status = DeviceCommand.Status.SENT

        logger.info(
            "device_commands_pull_succeeded",
            org_id=str(org.public_id),
            pulled_count=len(commands),
            command_ids=[str(cmd.public_id) for cmd in commands],
        )
        return commands


def ack_device_command(*, command: DeviceCommand, status: str, error: str = "") -> DeviceCommand:
    """
    Update command status based on Local Agent feedback.
    """
    logger.info(
        "device_command_ack_started",
        command_id=str(command.public_id),
        current_status=command.status,
        new_status=status,
    )
    # Persist agent result. FAILED increments retries and stores the error for audit.
    command.status = status
    if status == DeviceCommand.Status.FAILED:
        command.last_error = error
        command.retries = command.retries + 1
        if command.retries < command.max_retries:
            delay_seconds = _compute_retry_delay_seconds(command.retries)
            command.next_attempt_at = timezone.now() + timedelta(seconds=delay_seconds)
        else:
            command.next_attempt_at = None
    command.save(update_fields=["status", "last_error", "retries", "next_attempt_at", "updated_at"])
    logger.info(
        "device_command_ack_succeeded",
        command_id=str(command.public_id),
        status=command.status,
        retries=command.retries,
        has_next_attempt=command.next_attempt_at is not None,
    )
    return command


def release_due_device_commands(*, org) -> int:
    """
    Move retryable commands back to PENDING when they are due again.

    This also recovers commands stuck in SENT after an agent/request crash.
    """
    now = timezone.now()
    stale_sent_before = now - timedelta(
        seconds=getattr(settings, "DEVICE_COMMANDS_RETRY_BASE_SECONDS", 10)
    )
    released = (
        DeviceCommand.objects
        .filter(
            org=org,
            retries__lt=models.F("max_retries"),
        )
        .exclude(command_type__in=_MANUAL_RETRY_ONLY_COMMAND_TYPES)
        .filter(
            Q(
                status=DeviceCommand.Status.FAILED,
                next_attempt_at__isnull=False,
                next_attempt_at__lte=now,
            )
            | Q(
                status=DeviceCommand.Status.SENT,
                updated_at__lte=stale_sent_before,
            )
        )
        .update(status=DeviceCommand.Status.PENDING)
    )
    logger.info(
        "device_commands_release_due_completed",
        org_id=str(org.public_id),
        released_count=released,
    )
    return released
