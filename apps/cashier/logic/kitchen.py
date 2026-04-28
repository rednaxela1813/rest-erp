"""
Kitchen board helpers.
"""

from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404

from apps.orders.models import KitchenTicket
from config.orgs.models import Organization

UPDATABLE_TICKET_STATUSES = {
    KitchenTicket.Status.IN_PROGRESS,
    KitchenTicket.Status.DONE,
    KitchenTicket.Status.CANCELLED,
}


class InvalidKitchenTicketStatus(ValueError):
    pass


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


def claim_next_ticket(*, org: Organization) -> KitchenTicket | None:
    with transaction.atomic():
        ticket = (
            KitchenTicket.objects.select_for_update()
            .filter(org=org, status=KitchenTicket.Status.PENDING)
            .order_by("created_at", "id")
            .first()
        )
        if ticket:
            ticket.status = KitchenTicket.Status.IN_PROGRESS
            ticket.save(update_fields=["status", "updated_at"])
        return ticket


def update_ticket_status(*, org: Organization, public_id, status: str) -> KitchenTicket:
    if status not in UPDATABLE_TICKET_STATUSES:
        raise InvalidKitchenTicketStatus(status)

    ticket = get_object_or_404(KitchenTicket, org=org, public_id=public_id)
    ticket.status = status
    ticket.save(update_fields=["status", "updated_at"])
    return ticket
