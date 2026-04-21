"""
Kitchen board helpers.
"""

from __future__ import annotations

from apps.orders.models import KitchenTicket
from config.orgs.models import Organization


def kitchen_context(org: Organization) -> dict:
    """Собирает контекст для кухонного экрана."""
    pending = (
        KitchenTicket.objects.filter(org=org, status=KitchenTicket.Status.PENDING)
        .select_related("order", "product")
        .order_by("created_at", "id")
    )
    in_progress = (
        KitchenTicket.objects.filter(org=org, status=KitchenTicket.Status.IN_PROGRESS)
        .select_related("order", "product")
        .order_by("created_at", "id")
    )
    return {
        "pending_tickets": pending,
        "in_progress_tickets": in_progress,
    }
