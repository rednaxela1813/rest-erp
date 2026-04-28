"""
Kitchen board helpers.
"""

from __future__ import annotations

from apps.orders.logic.kitchen_tickets import in_progress_tickets, pending_tickets
from config.orgs.models import Organization


def kitchen_context(org: Organization) -> dict:
    """Собирает контекст для кухонного экрана."""
    return {
        "pending_tickets": pending_tickets(org=org),
        "in_progress_tickets": in_progress_tickets(org=org),
    }
