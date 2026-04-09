# apps/orders/api_views.py

from django.shortcuts import get_object_or_404
import inspect
import structlog

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import transaction
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from config.orgs.org_context import get_request_org
from config.orgs.permissions import IsOrgMemberReadOnlyOrOrgAdmin

from .logic.cancel_draft_order import cancel_draft_order
from .logic.cancel_order import cancel_order
from .logic.refund_order import refund_paid_order
from .logic.storno_order import storno_paid_order
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
        return Order.objects.filter(org=org).order_by("id")

    def perform_create(self, serializer):
        org = get_request_org(self.request)
        serializer.save(org=org)


class OrderItemListApi(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]
    serializer_class = OrderItemSerializer

    def get_queryset(self):
        org = get_request_org(self.request)
        order_public_id = self.kwargs["order_public_id"]

        # гарантируем org-scope через Order
        order = Order.objects.get(org=org, public_id=order_public_id)
        return OrderItem.objects.filter(order=order).order_by("id")


class OrderItemListCreateApi(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def get_order(self):
        org = get_request_org(self.request)
        return get_object_or_404(Order, org=org, public_id=self.kwargs["order_public_id"])

    def get_queryset(self):
        order = self.get_order()
        return OrderItem.objects.filter(order=order).order_by("id")

    def get_serializer_class(self):
        if self.request.method == "POST":
            return OrderItemCreateSerializer
        return OrderItemSerializer

    def perform_create(self, serializer):
        order = self.get_order()

        if order.status != Order.STATUS_DRAFT:
            logger.warning(
                "order_item_create_rejected_non_draft_order",
                order_id=str(order.public_id),
                order_status=order.status,
            )
            raise ValidationError({"order": "Cannot modify items for non-draft order."})

        serializer.save(order=order)

        order.recompute_totals()
        order.save(update_fields=["subtotal", "tax_total", "total", "updated_at"])


class OrderDetailApi(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]
    serializer_class = OrderSerializer
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        org = get_request_org(self.request)
        return Order.objects.filter(org=org)
    
    def _call_usecase(self, fn, *, order):
        """
        Совместимость:
        - старые тесты monkeypatch могут подменять use-case без параметра actor
        - новые use-case принимают actor (для истории статусов)
        """
        sig = inspect.signature(fn)
        if "actor" in sig.parameters:
            return fn(order=order, actor=self.request.user)
        return fn(order=order)

    def perform_update(self, serializer):
        order = self.get_object()

        if "status" not in serializer.validated_data:
            serializer.save()
            return

        new_status = serializer.validated_data["status"]
        old_status = order.status

        if new_status == Order.STATUS_PAID:
            logger.warning(
                "order_update_rejected_direct_paid_transition",
                order_id=str(order.public_id),
                old_status=old_status,
                new_status=new_status,
            )
            raise ValidationError(
                {"status": ["Direct order payment is blocked. Use payment capture endpoint."]}
            )

        if new_status == Order.STATUS_CANCELLED:
            if old_status == Order.STATUS_DRAFT:
                updated = self._call_usecase(cancel_draft_order, order=order)
                serializer.instance = updated
                return

            updated = self._call_usecase(cancel_order, order=order)
            serializer.instance = updated
            return

        serializer.save()

class OrderStatusEventListApi(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]
    serializer_class = OrderStatusEventSerializer

    def get_queryset(self):
        org = get_request_org(self.request)
        order_public_id = self.kwargs["public_id"]

        # гарантируем org-scope через Order
        order = get_object_or_404(Order, org=org, public_id=order_public_id)

        return (
            OrderStatusEvent.objects
            .filter(org=org, order=order)
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
        order = get_object_or_404(Order, org=org, public_id=public_id)
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
        order = get_object_or_404(Order, org=org, public_id=public_id)
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
        qs = (
            KitchenTicket.objects
            .filter(org=org)
            .select_related("order", "product")
            .order_by("created_at", "id")
        )
        status_param = self.request.query_params.get("status")
        if status_param:
            statuses = [s.strip() for s in status_param.split(",") if s.strip()]
            qs = qs.filter(status__in=statuses)
        else:
            qs = qs.filter(status=KitchenTicket.Status.PENDING)
        return qs


class KitchenTicketUpdateApi(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    def get_queryset(self):
        org = get_request_org(self.request)
        return KitchenTicket.objects.filter(org=org).select_related("order", "product")

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return KitchenTicketUpdateSerializer
        return KitchenTicketSerializer


class KitchenTicketClaimNextApi(APIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def post(self, request):
        org = get_request_org(request)
        with transaction.atomic():
            ticket = (
                KitchenTicket.objects
                .select_for_update()
                .filter(org=org, status=KitchenTicket.Status.PENDING)
                .order_by("created_at", "id")
                .select_related("order", "product")
                .first()
            )
            if not ticket:
                logger.info(
                    "kitchen_ticket_claim_next_empty",
                    org_id=str(org.public_id),
                    user_id=str(request.user.id),
                )
                return Response(status=status.HTTP_204_NO_CONTENT)
            ticket.status = KitchenTicket.Status.IN_PROGRESS
            ticket.save(update_fields=["status", "updated_at"])
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
        claimed = None
        with transaction.atomic():
            claimed = (
                KitchenTicket.objects
                .select_for_update()
                .filter(org=org, status=KitchenTicket.Status.PENDING)
                .order_by("created_at", "id")
                .select_related("order", "product")
                .first()
            )
            if claimed:
                claimed.status = KitchenTicket.Status.IN_PROGRESS
                claimed.save(update_fields=["status", "updated_at"])

        pending = (
            KitchenTicket.objects
            .filter(org=org, status=KitchenTicket.Status.PENDING)
            .select_related("order", "product")
            .order_by("created_at", "id")
        )
        in_progress = (
            KitchenTicket.objects
            .filter(org=org, status=KitchenTicket.Status.IN_PROGRESS)
            .select_related("order", "product")
            .order_by("created_at", "id")
        )

        payload = {
            "claimed": KitchenTicketSerializer(claimed).data if claimed else None,
            "pending": KitchenTicketSerializer(pending, many=True).data,
            "in_progress": KitchenTicketSerializer(in_progress, many=True).data,
        }
        return Response(payload)
