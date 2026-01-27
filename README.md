# Orders / Inventory Core (Django, TDD)

## 📌 Описание проекта

Этот проект — **ядро системы заказов (Orders) и управления складом (Inventory)**,
разрабатываемое как часть коммерческого Django-продукта (SaaS / ERP / POS-системы).

Цель — получить **строго корректную, конкурентно-безопасную доменную модель заказов**,
которую можно использовать:

* в POS-системах,
* в e-commerce,
* во внутренних ERP-процессах,
* как базу для бухгалтерии и отчётности.

Проект разрабатывается **строго через TDD**, с приоритетом:

* корректности,
* предсказуемости,
* отказоустойчивости,
* прозрачных бизнес-инвариантов.

---

## 🧱 Технологический стек

* **Python 3.13**
* **Django**
* **Django REST Framework**
* **PostgreSQL**
* **pytest + pytest-django**
* **Docker / docker-compose**
* Row-level locking (`SELECT ... FOR UPDATE`)
* Явные use-case’ы (command-style)

---

## 🧠 Архитектурные принципы

### 1. Command / Use-case driven design

Любое бизнес-действие оформлено как **явный use-case**:

* `pay_order`
* `cancel_order`
* `cancel_draft_order`

❌ Нет “магии” в `serializer.save()`
❌ Нет бизнес-логики в `views`
❌ Нет побочных эффектов в моделях

✅ Всё важное — в use-case’ах

---

### 2. FSM (Finite State Machine) для статусов заказа

Статус заказа — **строгая конечная автоматная модель**:

```
draft → paid → cancelled
draft → cancelled
```

* Все разрешённые переходы описаны в одном месте: `status_fsm.py`
* Один источник правды для:

  * API
  * use-case’ов
  * будущего UI

FSM используется **и в API-контрактах, и в бизнес-логике**.

---

### 3. Конкурентная безопасность (critical)

Проект **безопасен для параллельных запросов**:

* `select_for_update()` на:

  * Order (оплата / отмена)
  * Product (списание / возврат склада)
* Все критические операции — внутри `transaction.atomic()`
* Повторные запросы (double-pay / double-cancel) корректно обрабатываются

---

### 4. Агрегированная работа со складом

Склад **никогда не списывается по позициям**:

* qty агрегируется по `product_id`
* списание / возврат выполняется **один раз на продукт**
* предотвращает:

  * double-write,
  * race-conditions,
  * отрицательные остатки

---

### 5. TDD как основной процесс

Каждое поведение закреплено тестами:

* happy-path
* double-actions
* rollback при ошибках
* row-level locking
* idempotency

Тесты — **часть контракта**, а не “проверка после”.

---

## 📂 Структура приложения

```
apps/orders/
├── api_views.py              # REST API (тонкий слой)
├── serializers.py            # API-контракты + FSM
├── models.py                 # Order, OrderItem (без бизнес-логики)
├── logic/
│   ├── pay_order.py          # draft -> paid + stock debit
│   ├── cancel_order.py       # paid -> cancelled + stock refund
│   ├── cancel_draft_order.py # draft -> cancelled (без склада)
│   └── status_fsm.py         # FSM статусов
└── tests/
    ├── test_orders_pay.py
    ├── test_orders_double_pay.py
    ├── test_orders_cancel_refund.py
    ├── test_orders_double_cancel_usecase.py
    ├── test_orders_cancel_rollback.py
    ├── test_orders_stock_locking.py
    └── ...
```

---

## ✅ Что уже реализовано

### Заказы

* ✔️ Создание заказа (`draft`)
* ✔️ Добавление позиций только в `draft`
* ✔️ Пересчёт итогов заказа

### Оплата (`pay_order`)

* ✔️ Только `draft → paid`
* ✔️ Запрет `paid → paid`
* ✔️ Проверка наличия позиций
* ✔️ Агрегированное списание склада
* ✔️ Row-lock на Order и Product
* ✔️ Полный rollback при ошибке
* ✔️ Idempotency key для безопасного повторного создания платежа

### Фискальные документы

* ✔️ `FiscalReceipt` создаётся после успешной оплаты картой (capture)
* ✔️ Хранит `uid`, `raw_payload`, `total`, `tax_total`

### Отмена

* ✔️ `draft → cancelled` (без склада)
* ✔️ `paid → cancelled` (refund inventory)
* ✔️ Запрет повторной отмены
* ✔️ Запрет `cancelled → paid`
* ✔️ Атомарность возврата склада

### API-контракты

* ✔️ FSM-валидация статусов
* ✔️ Use-case only commands
* ✔️ Предсказуемые 400-ошибки
* ✔️ Нет двойных сохранений

### Тесты

* ✔️ Все переходы статусов
* ✔️ Double-pay
* ✔️ Double-cancel
* ✔️ Rollback при частичном сбое
* ✔️ Проверка `select_for_update`
* ✔️ Идемпотентность

---

## 🔁 Идемпотентность платежей

Повторный вызов создания платежа с одинаковыми параметрами не создаёт дубликат.
Используется `idempotency_key`, уникальный в рамках организации.

Правила:
* если ключ уже использован с теми же параметрами — возвращаем тот же платеж;
* если ключ уже использован с другими параметрами — ошибка;
* ключ уникален в рамках `org`.

Use-case: `start_payment` (создание payment intent).

API:
* `POST /api/v1/payments/start/` — создаёт (или возвращает) платеж по `idempotency_key`.

---

## 🚧 Что предстоит сделать дальше

### Ближайшие шаги (ядро)

1. **Явный Status History**

   * таблица истории переходов
   * audit-trail для бухгалтерии

2. **Order totals freeze**

   * запрет изменения цен после `paid`
   * защита от “подмены” данных

3. **Soft-delete / archive**

   * архивирование cancelled заказов
   * фильтрация в API

4. **Permissions / roles**

   * кто может платить
   * кто может отменять
   * POS vs admin

---

### Следующий уровень (ERP)

5. **Payments abstraction**

   * cash / card / online
   * внешний payment provider

6. **Accounting integration**

   * проводки при `paid`
   * проводки при `cancelled`

7. **Stock movements table**

   * вместо прямого изменения `stock_qty`
   * полноценный складской журнал

8. **Async processing**

   * Celery / background jobs
   * защита от таймаутов POS

---

### UI / API

9. **Allowed next statuses API**

   * `GET /orders/{id}/available-actions`

10. **OpenAPI / DRF Spectacular**

    * документирование контрактов

---

## 🎯 Философия проекта

Этот проект **осознанно сложнее CRUD**.

Он проектируется так, чтобы:

* выдерживать реальные нагрузки,
* не ломаться при параллельных запросах,
* быть расширяемым,
* быть пригодным для денег и склада.

Это **не учебный пример**, а фундамент для коммерческого продукта.

---

## 🧪 Как запускать тесты

```bash
docker compose run --rm web pytest -q
```

---

## 👤 Статус

Проект в **активной разработке**, ядро заказов стабилизировано,
следующий этап — **расширение доменной модели**.
