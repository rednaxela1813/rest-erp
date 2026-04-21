from rest_framework.permissions import IsAuthenticated
from decimal import Decimal
import structlog

from rest_framework import serializers
from rest_framework import status as drf_status
from rest_framework.response import Response
from rest_framework.views import APIView

from config.orgs.org_context import get_request_org
from config.orgs.permissions import IsOrgMemberReadOnlyOrOrgAdmin
from apps.payments.logic.capture_payment import capture_payment
from apps.payments.logic.device_commands import ack_device_command, pull_device_commands
from apps.payments.logic.start_payment import start_payment
from apps.payments.logic.shift import close_shift, open_shift, shift_report
from apps.payments.models import CashierSession, DeviceCommand, OrderPayment, Terminal
from apps.orders.models import Order
from django.shortcuts import get_object_or_404
from django.db.models import Count

logger = structlog.get_logger(__name__)


class PaymentStartSerializer(serializers.Serializer):
    order = serializers.UUIDField()
    tender = serializers.ChoiceField(choices=OrderPayment.Tender.choices)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField(max_length=3)
    idempotency_key = serializers.CharField(max_length=64, required=False, allow_blank=True)

    def validate(self, attrs):
        request = self.context["request"]
        org = get_request_org(request)

        order = get_object_or_404(Order, org=org, public_id=attrs["order"])
        attrs["order_obj"] = order

        if order.total != attrs["amount"]:
            logger.warning(
                "payment_start_amount_mismatch",
                order_id=str(order.public_id),
                expected_amount=str(order.total),
                provided_amount=str(attrs["amount"]),
            )
            raise serializers.ValidationError({"amount": ["Amount must match order total."]})

        return attrs


class PaymentStartApi(APIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def post(self, request):
        serializer = PaymentStartSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        order = serializer.validated_data["order_obj"]
        idempotency_key = serializer.validated_data.get("idempotency_key") or None

        payment = start_payment(
            order=order,
            tender=serializer.validated_data["tender"],
            amount=serializer.validated_data["amount"],
            currency=serializer.validated_data["currency"],
            idempotency_key=idempotency_key,
        )
        logger.info(
            "payment_start_api_succeeded",
            payment_id=str(payment.public_id),
            order_id=str(payment.order.public_id),
            user_id=str(request.user.id),
        )

        return Response(
            {
                "payment": str(payment.public_id),
                "status": payment.status,
                "order": str(payment.order.public_id),
                "amount": str(payment.amount),
                "currency": payment.currency,
            }
        )


class PaymentCaptureApi(APIView):
    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def post(self, request, public_id):
        org = get_request_org(request)
        payment = get_object_or_404(OrderPayment, org=org, public_id=public_id)
        logger.info(
            "payment_capture_api_requested",
            payment_id=str(payment.public_id),
            order_id=str(payment.order.public_id),
            user_id=str(request.user.id),
        )

        payment = capture_payment(payment=payment, actor=request.user)
        payment.refresh_from_db()
        payment.order.refresh_from_db()

        return Response(
            {
                "payment": str(payment.public_id),
                "payment_status": payment.status,
                "order": str(payment.order.public_id),
                "order_status": payment.order.status,
            }
        )


class DeviceCommandSerializer(serializers.ModelSerializer):
    """
    Read-only representation for Local Agent pull.
    """

    order = serializers.UUIDField(source="order.public_id", read_only=True)
    payment = serializers.UUIDField(source="payment.public_id", read_only=True)

    class Meta:
        model = DeviceCommand
        fields = [
            "public_id",
            "command_type",
            "status",
            "payload",
            "order",
            "payment",
            "retries",
            "max_retries",
            "created_at",
        ]
        read_only_fields = fields


class DeviceCommandAckSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[DeviceCommand.Status.ACKED, DeviceCommand.Status.FAILED])
    error = serializers.CharField(required=False, allow_blank=True)


class DeviceCommandPullApi(APIView):
    """
    Local Agent pulls pending commands for execution.
    """

    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def get(self, request):
        org = get_request_org(request)
        # Default batch size keeps agent load predictable.
        limit = int(request.query_params.get("limit", "50"))
        logger.info(
            "device_command_pull_api_requested",
            org_id=str(org.public_id),
            user_id=str(request.user.id),
            limit=limit,
        )

        # Pull will lock and mark commands as SENT to avoid duplicates.
        commands = pull_device_commands(org=org, limit=limit)
        data = DeviceCommandSerializer(commands, many=True).data
        return Response(data)


class DeviceCommandAckApi(APIView):
    """
    Local Agent acknowledges execution result (ACK/FAIL).
    """

    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def post(self, request, public_id):
        org = get_request_org(request)
        command = get_object_or_404(DeviceCommand, org=org, public_id=public_id)

        serializer = DeviceCommandAckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Persist agent outcome (ACKED/FAILED + optional error text).
        ack_device_command(
            command=command,
            status=serializer.validated_data["status"],
            error=serializer.validated_data.get("error", ""),
        )
        logger.info(
            "device_command_ack_api_succeeded",
            org_id=str(org.public_id),
            user_id=str(request.user.id),
            command_id=str(command.public_id),
            status=serializer.validated_data["status"],
        )

        return Response(status=drf_status.HTTP_204_NO_CONTENT)


class PaymentStatusApi(APIView):
    """
    Read-only payment status with device-command delivery overview.
    """

    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def get(self, request, public_id):
        org = get_request_org(request)
        payment = get_object_or_404(OrderPayment, org=org, public_id=public_id)

        counts = {
            DeviceCommand.Status.PENDING: 0,
            DeviceCommand.Status.SENT: 0,
            DeviceCommand.Status.ACKED: 0,
            DeviceCommand.Status.FAILED: 0,
        }
        for row in DeviceCommand.objects.filter(payment=payment).values("status").annotate(count=Count("id")):
            counts[row["status"]] = row["count"]

        return Response(
            {
                "payment": str(payment.public_id),
                "status": payment.status,
                "capture_status": payment.capture_status,
                "fiscal_status": payment.fiscal_status,
                "failure_reason": payment.failure_reason,
                "device_command_counts": counts,
            }
        )


class PaymentManualResolutionSerializer(serializers.Serializer):
    capture_status = serializers.ChoiceField(choices=OrderPayment.CaptureStatus.choices, required=False)
    fiscal_status = serializers.ChoiceField(choices=OrderPayment.FiscalStatus.choices, required=False)
    failure_reason = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs:
            logger.warning("payment_manual_resolution_empty_payload")
            raise serializers.ValidationError({"detail": ["At least one field is required."]})
        return attrs


class PaymentManualResolutionApi(APIView):
    """
    Manual override for outage resolution (admin/owner only).
    """

    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def post(self, request, public_id):
        org = get_request_org(request)
        payment = get_object_or_404(OrderPayment, org=org, public_id=public_id)

        serializer = PaymentManualResolutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updates = {}
        if "capture_status" in serializer.validated_data:
            updates["capture_status"] = serializer.validated_data["capture_status"]
        if "fiscal_status" in serializer.validated_data:
            updates["fiscal_status"] = serializer.validated_data["fiscal_status"]
        if "failure_reason" in serializer.validated_data:
            updates["failure_reason"] = serializer.validated_data["failure_reason"]

        for field, value in updates.items():
            setattr(payment, field, value)
        payment.save(update_fields=[*updates.keys(), "updated_at"])
        logger.info(
            "payment_manual_resolution_api_updated",
            org_id=str(org.public_id),
            user_id=str(request.user.id),
            payment_id=str(payment.public_id),
            updated_fields=sorted(updates.keys()),
        )

        return Response(
            {
                "payment": str(payment.public_id),
                "capture_status": payment.capture_status,
                "fiscal_status": payment.fiscal_status,
                "failure_reason": payment.failure_reason,
            }
        )


class FiscalReceiptsHealthApi(APIView):
    """
    Health endpoint for unsent fiscal receipts (device commands).
    """

    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def get(self, request):
        org = get_request_org(request)

        qs = DeviceCommand.objects.filter(
            org=org,
            command_type__in=[
                DeviceCommand.Type.FISCALIZE_SALE,
                DeviceCommand.Type.FISCALIZE_REFUND,
                DeviceCommand.Type.FISCALIZE_STORNO,
            ],
        ).exclude(status=DeviceCommand.Status.ACKED)

        status_counts = {
            DeviceCommand.Status.PENDING: 0,
            DeviceCommand.Status.SENT: 0,
            DeviceCommand.Status.FAILED: 0,
        }
        for row in qs.values("status").annotate(count=Count("id")):
            status_counts[row["status"]] = row["count"]

        oldest = qs.order_by("created_at").first()

        return Response(
            {
                "unsent_total": qs.count(),
                "status_counts": status_counts,
                "oldest_created_at": oldest.created_at if oldest else None,
                "oldest_public_id": str(oldest.public_id) if oldest else None,
            }
        )


class EkasaHealthApi(APIView):
    """
    Health endpoint for eKasa device command queue and errors.
    """

    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def get(self, request):
        org = get_request_org(request)

        qs = DeviceCommand.objects.filter(
            org=org,
            command_type__in=[
                DeviceCommand.Type.FISCALIZE_SALE,
                DeviceCommand.Type.FISCALIZE_REFUND,
                DeviceCommand.Type.FISCALIZE_STORNO,
            ],
        )

        status_counts = {
            DeviceCommand.Status.PENDING: 0,
            DeviceCommand.Status.SENT: 0,
            DeviceCommand.Status.ACKED: 0,
            DeviceCommand.Status.FAILED: 0,
        }
        for row in qs.values("status").annotate(count=Count("id")):
            status_counts[row["status"]] = row["count"]

        failed_qs = qs.filter(status=DeviceCommand.Status.FAILED)
        oldest_failed = failed_qs.order_by("created_at").first()
        oldest_pending = qs.filter(status=DeviceCommand.Status.PENDING).order_by("created_at").first()

        return Response(
            {
                "total": qs.count(),
                "status_counts": status_counts,
                "failed_total": failed_qs.count(),
                "oldest_failed_created_at": oldest_failed.created_at if oldest_failed else None,
                "oldest_failed_public_id": str(oldest_failed.public_id) if oldest_failed else None,
                "oldest_pending_created_at": oldest_pending.created_at if oldest_pending else None,
                "oldest_pending_public_id": str(oldest_pending.public_id) if oldest_pending else None,
            }
        )


class ShiftOpenSerializer(serializers.Serializer):
    terminal = serializers.UUIDField()
    opening_cash = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)


class ShiftCloseSerializer(serializers.Serializer):
    closing_cash = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)


class ShiftOpenApi(APIView):
    """
    Open a cashier shift for a terminal.

    This uses CashierSession under the hood but exposes a clean API contract.
    """

    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def post(self, request):
        serializer = ShiftOpenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        org = get_request_org(request)
        terminal = get_object_or_404(Terminal, org=org, public_id=serializer.validated_data["terminal"])

        opening_cash = serializer.validated_data.get("opening_cash")
        if opening_cash is None:
            opening_cash = Decimal("0.00")

        session = open_shift(
            org=org,
            terminal=terminal,
            cashier=request.user,
            opening_cash=opening_cash,
        )

        return Response(
            {
                "shift": str(session.public_id),
                "status": session.status,
                "terminal": str(terminal.public_id),
                # User model has no public_id; expose internal id for now.
                "cashier": str(session.cashier_id),
                "opened_at": session.opened_at,
            }
        )


class ShiftCloseApi(APIView):
    """
    Close an open shift.
    """

    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def post(self, request, public_id):
        serializer = ShiftCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        org = get_request_org(request)
        session = get_object_or_404(CashierSession, org=org, public_id=public_id)

        closing_cash = serializer.validated_data.get("closing_cash")
        if closing_cash is None:
            closing_cash = Decimal("0.00")

        session = close_shift(session=session, closing_cash=closing_cash)

        return Response(
            {
                "shift": str(session.public_id),
                "status": session.status,
                "closed_at": session.closed_at,
                "cash_drawer_end": str(session.cash_drawer_end or Decimal("0.00")),
            }
        )


class ShiftReportApi(APIView):
    """
    Return shift totals for payments and taxes.
    """

    permission_classes = [IsAuthenticated, IsOrgMemberReadOnlyOrOrgAdmin]

    def get(self, request, public_id):
        org = get_request_org(request)
        session = get_object_or_404(CashierSession, org=org, public_id=public_id)

        totals = shift_report(session=session)

        return Response(
            {
                "shift": str(session.public_id),
                "status": session.status,
                "terminal": str(session.terminal.public_id),
                "cashier": str(session.cashier_id),
                "opened_at": session.opened_at,
                "closed_at": session.closed_at,
                "totals": {
                    "payments_total": str(totals["payments_total"]),
                    "tax_total": str(totals["tax_total"]),
                    "by_tender": {k: str(v) for k, v in totals["by_tender"].items()},
                    "by_tax_rate": [
                        {"rate": item["rate"], "tax_total": str(item["tax_total"])} for item in totals["by_tax_rate"]
                    ],
                },
            }
        )
