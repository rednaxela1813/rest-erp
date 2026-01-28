from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from apps.orders.models import Order
from apps.payments.admin import OrderPaymentAdmin
from apps.payments.models import OrderPayment


@pytest.mark.django_db
def test_admin_actions_update_capture_and_fiscal_statuses(org_factory):
    org = org_factory()
    order = Order.objects.create(org=org)
    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.AUTHORIZED,
        amount=Decimal("5.00"),
        currency="EUR",
        provider="manual",
    )

    User = get_user_model()
    admin_user = User.objects.create_superuser(
        email="admin@example.com",
        password="pass12345",
    )
    request = RequestFactory().post("/")
    request.user = admin_user
    # Enable message framework for admin actions.
    request.session = {}
    request._messages = FallbackStorage(request)

    model_admin = OrderPaymentAdmin(OrderPayment, admin.site)
    queryset = OrderPayment.objects.filter(id=payment.id)

    model_admin.mark_capture_confirmed(request, queryset)
    payment.refresh_from_db()
    assert payment.capture_status == OrderPayment.CaptureStatus.CONFIRMED

    model_admin.mark_fiscal_failed(request, queryset)
    payment.refresh_from_db()
    assert payment.fiscal_status == OrderPayment.FiscalStatus.FAILED
