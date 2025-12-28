# tests/test_capture_payment_usecase.py
import pytest
from decimal import Decimal
from rest_framework.exceptions import ValidationError


@pytest.mark.django_db
def test_capture_payment_transitions_to_captured_and_creates_event(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.models import OrderPayment, PaymentEvent
    from apps.payments.logic.capture_payment import capture_payment

    order = Order.objects.create(org=org)

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.AUTHORIZED,
        amount=Decimal("12.34"),
        currency="EUR",
        provider="manual",
    )

    captured = capture_payment(payment=payment, actor=user)

    captured.refresh_from_db()
    assert captured.status == OrderPayment.Status.CAPTURED

    ev = PaymentEvent.objects.filter(payment=captured).order_by("-created_at").first()
    assert ev is not None
    assert ev.org_id == org.id
    assert ev.actor_id == user.id
    assert ev.action == "capture"
    assert ev.from_status == OrderPayment.Status.AUTHORIZED
    assert ev.to_status == OrderPayment.Status.CAPTURED


@pytest.mark.django_db
def test_capture_payment_is_strict_and_fails_if_already_captured(admin_client):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.models import OrderPayment
    from apps.payments.logic.capture_payment import capture_payment

    order = Order.objects.create(org=org)

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.CAPTURED,
        amount=Decimal("10.00"),
        currency="EUR",
        provider="manual",
    )

    with pytest.raises(ValidationError) as e:
        capture_payment(payment=payment, actor=user)

    # строгий инвариант: captured -> captured запрещён
    assert e.value.detail == {"status": ["Payment is already captured."]}


@pytest.mark.django_db
def test_capture_payment_uses_row_lock_select_for_update(admin_client, monkeypatch):
    client, user, org = admin_client

    from apps.orders.models import Order
    from apps.payments.models import OrderPayment
    from apps.payments.logic.capture_payment import capture_payment

    order = Order.objects.create(org=org)

    payment = OrderPayment.objects.create(
        org=org,
        order=order,
        tender=OrderPayment.Tender.CARD,
        status=OrderPayment.Status.AUTHORIZED,
        amount=Decimal("10.00"),
        currency="EUR",
        provider="manual",
    )

    # Проверяем, что внутри use-case есть row-lock.
    # Патчим общий QuerySet.select_for_update, но считаем вызовы только для payments.OrderPayment.
    from django.db.models.query import QuerySet

    original = QuerySet.select_for_update
    called = {"count": 0}

    def spy_select_for_update(self, *args, **kwargs):
        # ограничиваем проверку только нужной моделью, чтобы не словить “шум” от других запросов
        if getattr(self, "model", None) is OrderPayment:
            called["count"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(QuerySet, "select_for_update", spy_select_for_update)

    capture_payment(payment=payment, actor=user)

    assert called["count"] >= 1
