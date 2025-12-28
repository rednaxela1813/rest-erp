# apps/orders/api_views.py

from django.shortcuts import get_object_or_404
import inspect

from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from config.orgs.org_context import get_request_org
from config.orgs.permissions import IsOrgMemberReadOnlyOrOrgAdmin

from .logic.cancel_draft_order import cancel_draft_order
from .logic.cancel_order import cancel_order
from .logic.pay_order import pay_order
from .models import Order, OrderItem, OrderStatusEvent
from .serializers import (
    OrderItemCreateSerializer,
    OrderItemSerializer,
    OrderSerializer,
    OrderStatusEventSerializer,
)


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
            updated = self._call_usecase(pay_order, order=order)
            serializer.instance = updated
            return

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
