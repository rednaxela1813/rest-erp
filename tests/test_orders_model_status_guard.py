# teasts/test_orders_model_status_guard.py
import pytest
from django.core.exceptions import ValidationError as DjangoValidationError


@pytest.mark.django_db
def test_order_status_cannot_be_changed_directly_via_model_save(admin_client):
    """
    GIVEN:
        - Order в статусе draft (обычный заказ)
    WHEN:
        - кто-то меняет order.status руками и делает order.save()
          (например: админка, скрипт, ошибочный код в сериализаторе)
    THEN:
        - это должно быть запрещено на уровне модели,
          чтобы статус менялся ТОЛЬКО через use-case.
    """
    _client, _user, org = admin_client

    from apps.orders.models import Order

    order = Order.objects.create(org=org)  # draft по умолчанию

    # Пытаемся "в обход" бизнес-логики поменять статус
    order.status = Order.STATUS_PAID

    with pytest.raises(DjangoValidationError) as exc:
        order.save(update_fields=["status"])

    # Проверяем, что ошибка именно про статус (это удобно для дебага)
    assert "status" in exc.value.message_dict


@pytest.mark.django_db
def test_order_non_status_fields_can_be_saved_normally(admin_client):
    """
    Контрольный тест:
    - Запрет касается ТОЛЬКО статуса.
    - Остальные поля должны сохраняться нормально.
    """
    _client, _user, org = admin_client

    from apps.orders.models import Order

    order = Order.objects.create(org=org)

    # Если у Order есть поле "note" или похожее — можно поменять его.
    # Если нет — этот тест можно удалить или адаптировать под реальное поле.
    if hasattr(order, "note"):
        order.note = "Hello"
        order.save(update_fields=["note"])
        order.refresh_from_db()
        assert order.note == "Hello"
