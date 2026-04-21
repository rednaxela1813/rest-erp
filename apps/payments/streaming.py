from __future__ import annotations

import json

import redis
from django.conf import settings

from apps.payments.models import DeviceCommand


def get_redis_client() -> redis.Redis:
    """
    Build a Redis client for device command streaming.
    """
    return redis.Redis.from_url(settings.DEVICE_COMMANDS_REDIS_URL, decode_responses=True)


def _serialize_command(command: DeviceCommand) -> dict[str, str]:
    """
    Serialize DeviceCommand into flat string fields for Redis Streams.

    Redis Streams accept string values only, so we JSON-encode payloads.
    """
    order_public_id = str(command.order.public_id) if command.order is not None else ""
    payment_public_id = str(command.payment.public_id) if command.payment is not None else ""

    return {
        "public_id": str(command.public_id),
        "org_id": str(command.org_id),
        "command_type": command.command_type,
        "status": command.status,
        "payload": json.dumps(command.payload, ensure_ascii=True),
        "order": order_public_id,
        "payment": payment_public_id,
        "retries": str(command.retries),
        "max_retries": str(command.max_retries),
        "created_at": command.created_at.isoformat(),
    }


def publish_device_commands(commands: list[DeviceCommand]) -> int:
    """
    Publish commands into a Redis Stream for device agents.

    Returns the number of published commands.
    """
    if not commands:
        return 0

    client = get_redis_client()
    stream = settings.DEVICE_COMMANDS_STREAM
    maxlen = settings.DEVICE_COMMANDS_STREAM_MAXLEN

    for command in commands:
        payload = _serialize_command(command)
        # Use MAXLEN to prevent unbounded stream growth in long-lived installs.
        client.xadd(stream, payload, maxlen=maxlen, approximate=True)

    return len(commands)
