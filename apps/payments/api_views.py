from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from config.orgs.org_context import get_request_org
from config.orgs.permissions import IsOrgMemberReadOnlyOrOrgAdmin
from apps.payments.logic.capture_payment import capture_payment
from apps.payments.logic.start_payment import start_payment
from apps.payments.models import OrderPayment
from apps.orders.models import Order
from django.shortcuts import get_object_or_404


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
