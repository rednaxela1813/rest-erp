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


def kitchen_ticket_queryset(*, org: Organization):
    return KitchenTicket.objects.for_org(org).select_related("order", "product").order_by("created_at", "id")


def pending_tickets(*, org: Organization):
    return kitchen_ticket_queryset(org=org).filter(status=KitchenTicket.Status.PENDING)


def in_progress_tickets(*, org: Organization):
    return kitchen_ticket_queryset(org=org).filter(status=KitchenTicket.Status.IN_PROGRESS)


def filtered_tickets(*, org: Organization, status_param: str | None):
    queryset = kitchen_ticket_queryset(org=org)
    if status_param:
        statuses = [status.strip() for status in status_param.split(",") if status.strip()]
        return queryset.filter(status__in=statuses)
    return queryset.filter(status=KitchenTicket.Status.PENDING)


def claim_next_ticket(*, org: Organization) -> KitchenTicket | None:
    with transaction.atomic():
        ticket = (
            KitchenTicket.objects.select_for_update()
            .for_org(org)
            .filter(status=KitchenTicket.Status.PENDING)
            .order_by("created_at", "id")
            .select_related("order", "product")
            .first()
        )
        if ticket:
            ticket.status = KitchenTicket.Status.IN_PROGRESS
            ticket.save(update_fields=["status", "updated_at"])
        return ticket


def update_ticket_status(*, org: Organization, public_id, status: str) -> KitchenTicket:
    if status not in UPDATABLE_TICKET_STATUSES:
        raise InvalidKitchenTicketStatus(status)

    ticket = get_object_or_404(KitchenTicket.objects.for_org(org), public_id=public_id)
    ticket.status = status
    ticket.save(update_fields=["status", "updated_at"])
    return ticket


def ticket_queue(*, org: Organization) -> dict:
    return {
        "pending": pending_tickets(org=org),
        "in_progress": in_progress_tickets(org=org),
    }
