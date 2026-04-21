# project/backend/tests/test_orders_stock_concurrent.py
"""
Тест на конкурентное списание остатков.

Сценарий: на складе 1 бургер. Два «кассира» одновременно пытаются
его продать. Один должен успеть, второй — получить InsufficientStock.
Итоговый остаток не должен уйти в минус.

Почему transaction=True:
    Обычные тесты оборачивают всё в одну транзакцию и откатывают её в конце.
    При этом потоки не видят блокировок (select_for_update) друг друга —
    они все работают внутри одной транзакции теста.
    transaction=True отключает эту обёртку: каждая транзакция реальная,
    PostgreSQL честно блокирует строки между потоками.
    После теста pytest-django сам чистит БД через TRUNCATE — вручную
    ничего удалять не нужно и нельзя (сломает каскад PROTECT-зависимостей).
"""

import threading
from decimal import Decimal

import pytest

from apps.inventory.exceptions import InsufficientStock
from apps.inventory.services.deduct_stock import deduct_stock
from apps.inventory.services.receive_stock import receive_stock
from apps.inventory.models import StockLot
from apps.products.models import Product, Unit, TaxRate
from config.orgs.models import Organization


# transactional_db — специальная фикстура pytest-django для тестов с transaction=True.
# Она разрешает реальные коммиты внутри теста и делает TRUNCATE таблиц после него.
# Важно: НЕ пытаться удалять объекты вручную в teardown — из-за on_delete=PROTECT
# это сломает уборку. pytest-django сам всё почистит.


@pytest.fixture
def org(transactional_db):
    return Organization.objects.create(name="Concurrent Test Org")


@pytest.fixture
def product_with_one_unit(org):
    unit = Unit.objects.create(org=org, name="pcs")
    tax_rate = TaxRate.objects.create(org=org, name="VAT 20", rate=Decimal("20.00"))
    product = Product.objects.create(
        org=org,
        name="Last Burger",
        unit=unit,
        tax_rate=tax_rate,
        unit_price=Decimal("5.00"),
    )
    # Кладём на склад ровно 1 штуку
    receive_stock(
        org=org,
        product=product,
        initial_qty=Decimal("1.000"),
        unit_cost=Decimal("2.00"),
        label_code="LOT-LAST-BURGER",
    )
    return product


@pytest.mark.django_db(transaction=True)
def test_concurrent_deduct_only_one_succeeds(product_with_one_unit, org):
    """
    Два потока одновременно пытаются списать 1 бургер при остатке 1 шт.
    Ожидаемый результат:
    - ровно один поток успевает (successes == 1)
    - ровно один получает InsufficientStock (failures == 1)
    - итоговый remaining_qty партии == 0, не -1
    """
    product = product_with_one_unit
    results = []  # сюда каждый поток запишет "ok" или "insufficient_stock"
    results_lock = threading.Lock()  # потокобезопасная запись в общий список
    barrier = threading.Barrier(2)  # барьер синхронизирует старт обоих потоков

    def try_deduct():
        # Оба потока доходят до барьера и стартуют одновременно
        barrier.wait()
        try:
            deduct_stock(
                org=org,
                product=product,
                quantity=Decimal("1.000"),
                reason="order_paid",
                comment="concurrent_test",
            )
            with results_lock:
                results.append("ok")
        except InsufficientStock:
            with results_lock:
                results.append("insufficient_stock")

    threads = [threading.Thread(target=try_deduct) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Ровно один должен был успеть, ровно один — получить ошибку
    assert results.count("ok") == 1, f"Expected 1 success, got: {results}"
    assert results.count("insufficient_stock") == 1, f"Expected 1 failure, got: {results}"

    # Остаток должен быть ровно 0, не отрицательным
    lot = StockLot.objects.get(org=org, product=product)
    assert lot.remaining_qty == Decimal("0.000"), f"remaining_qty should be 0, got {lot.remaining_qty}"
    assert lot.status == StockLot.Status.DEPLETED


@pytest.mark.django_db(transaction=True)
def test_concurrent_deduct_both_fail_if_stock_zero(product_with_one_unit, org):
    """
    Сначала вручную списываем 1 шт. (остаток = 0).
    Затем два потока одновременно пытаются списать — оба должны получить
    InsufficientStock. Ни один не должен пройти.
    """
    product = product_with_one_unit

    # Предварительно опустошаем склад
    deduct_stock(
        org=org,
        product=product,
        quantity=Decimal("1.000"),
        reason="pre_deduct",
        comment="setup",
    )

    results = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def try_deduct():
        barrier.wait()
        try:
            deduct_stock(
                org=org,
                product=product,
                quantity=Decimal("1.000"),
                reason="order_paid",
                comment="concurrent_test",
            )
            with results_lock:
                results.append("ok")
        except InsufficientStock:
            with results_lock:
                results.append("insufficient_stock")

    threads = [threading.Thread(target=try_deduct) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("ok") == 0, f"Expected 0 successes, got: {results}"
    assert results.count("insufficient_stock") == 2
