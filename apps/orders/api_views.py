# apps/orders/api_views.py

from django.shortcuts import get_object_or_404

import structlog

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from config.orgs.org_context import get_request_org
from config.orgs.permissions import IsOrgMemberReadOnlyOrOrgAdmin

from .logic.api_order_actions import add_item_to_order_from_api, update_order_from_api
from .logic.kitchen_tickets import claim_next_ticket, filtered_tickets, ticket_queue
from apps.payments.logic.order_adjustments import refund_paid_order, storno_paid_order
from .models import KitchenTicket, Order, OrderItem, OrderStatusEvent
from .serializers import (
    KitchenTicketSerializer,
    KitchenTicketUpdateSerializer,
    OrderItemCreateSerializer,
    OrderItemSerializer,
    OrderSerializer,
    OrderStatusEventSerializer,
)

logger = structlog.get_logger(__name__)


class OrderListCreateApi(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]
    serializer_class = OrderSerializer

    def get_queryset(self):
        org = get_request_org(self.request)
        return Order.objects.for_org(org).order_by("id")

    def perform_create(self, serializer):
        org = get_request_org(self.request)
        serializer.save(org=org)


class OrderItemListCreateApi(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def get_order(self):
        org = get_request_org(self.request)
        return get_object_or_404(Order.objects.for_org(org), public_id=self.kwargs["order_public_id"])

    def get_queryset(self):
        order = self.get_order()
        return OrderItem.objects.filter(order=order).order_by("id")

    def get_serializer_class(self):
        if self.request.method == "POST":
            return OrderItemCreateSerializer
        return OrderItemSerializer

    def perform_create(self, serializer):
        order = self.get_order()
        add_item_to_order_from_api(order=order, serializer=serializer, logger=logger)


class OrderDetailApi(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]
    serializer_class = OrderSerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        org = get_request_org(self.request)
        return Order.objects.for_org(org)

    def perform_update(self, serializer):
        order = self.get_object()
        update_order_from_api(order=order, serializer=serializer, actor=self.request.user, logger=logger)


class OrderStatusEventListApi(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]
    serializer_class = OrderStatusEventSerializer

    def get_queryset(self):
        org = get_request_org(self.request)
        order_public_id = self.kwargs["public_id"]

        # гарантируем org-scope через Order
        order = get_object_or_404(Order.objects.for_org(org), public_id=order_public_id)

        return (
            OrderStatusEvent.objects.filter(org=org, order=order)
            .select_related("actor", "order")
            .order_by("-created_at", "-id")
        )


class OrderRefundApi(APIView):
    """
    Refund a paid order.

    This endpoint is intentionally narrow:
    - Requires org admin/owner (manager role in MVP)
    - Cancels the order (paid -> cancelled)
    - Creates fiscal receipt (refund) and enqueues device commands
    """

    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def post(self, request, public_id):
        org = get_request_org(request)
        order = get_object_or_404(Order.objects.for_org(org), public_id=public_id)
        logger.info(
            "order_refund_api_requested",
            org_id=str(org.public_id),
            order_id=str(order.public_id),
            user_id=str(request.user.id),
        )

        receipt = refund_paid_order(order=order, actor=request.user)
        order.refresh_from_db()

        return Response(
            {
                "order": str(order.public_id),
                "order_status": order.status,
                "receipt": str(receipt.public_id),
                "receipt_type": receipt.receipt_type,
            }
        )


class OrderStornoApi(APIView):
    """
    Storno a paid order.

    This endpoint is intentionally narrow:
    - Requires org admin/owner (manager role in MVP)
    - Cancels the order (paid -> cancelled)
    - Creates fiscal receipt (storno) and enqueues device commands
    """

    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def post(self, request, public_id):
        org = get_request_org(request)
        order = get_object_or_404(Order.objects.for_org(org), public_id=public_id)
        logger.info(
            "order_storno_api_requested",
            org_id=str(org.public_id),
            order_id=str(order.public_id),
            user_id=str(request.user.id),
        )

        receipt = storno_paid_order(order=order, actor=request.user)
        order.refresh_from_db()

        return Response(
            {
                "order": str(order.public_id),
                "order_status": order.status,
                "receipt": str(receipt.public_id),
                "receipt_type": receipt.receipt_type,
            }
        )


class KitchenTicketListApi(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]
    serializer_class = KitchenTicketSerializer

    def get_queryset(self):
        org = get_request_org(self.request)
        return filtered_tickets(org=org, status_param=self.request.query_params.get("status"))


class KitchenTicketUpdateApi(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        org = get_request_org(self.request)
        return KitchenTicket.objects.for_org(org).select_related("order", "product")

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return KitchenTicketUpdateSerializer
        return KitchenTicketSerializer


class KitchenTicketClaimNextApi(APIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def post(self, request):
        org = get_request_org(request)
        ticket = claim_next_ticket(org=org)
        if not ticket:
            logger.info(
                "kitchen_ticket_claim_next_empty",
                org_id=str(org.public_id),
                user_id=str(request.user.id),
            )
            return Response(status=status.HTTP_204_NO_CONTENT)

        logger.info(
            "kitchen_ticket_claim_next_succeeded",
            org_id=str(org.public_id),
            user_id=str(request.user.id),
            ticket_id=str(ticket.public_id),
        )
        return Response(KitchenTicketSerializer(ticket).data)


class KitchenTicketClaimNextWithQueueApi(APIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def post(self, request):
        org = get_request_org(request)
        claimed = claim_next_ticket(org=org)
        queue = ticket_queue(org=org)

        payload = {
            "claimed": KitchenTicketSerializer(claimed).data if claimed else None,
            "pending": KitchenTicketSerializer(queue["pending"], many=True).data,
            "in_progress": KitchenTicketSerializer(queue["in_progress"], many=True).data,
        }
        return Response(payload)
