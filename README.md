# ERP for Burger Backend

Django backend для ресторанного ERP/POS: организации, каталог, склад, рецептуры, заказы, оплаты, фискализация, кассовый UI и операционные панели.

## Состояние проекта

Backend уже представляет собой модульный монолит с несколькими прикладными доменами и общей PostgreSQL-базой.

Текущее покрытие:

- `config.users` — кастомный пользователь, JWT login/refresh/logout, `/auth/me/`
- `config.orgs` — организации, участники, org-context, org notes, орг-изоляция данных
- `config.dictionaries` — валюты, страны, seed-команда для словарей
- `apps.products` — единицы измерения, налоговые ставки, товары, bundle, варианты, add-ons
- `apps.partners` — контрагенты/поставщики
- `apps.equipment` — оборудование, связанное с орг-контекстом
- `apps.inventory` — складские партии, движения и локации
- `apps.recipes` — рецептуры и ингредиенты для списания
- `apps.orders` — заказы, позиции, addons, события статусов, kitchen tickets
- `apps.payments` — терминалы, провайдеры, платежи, capture/fiscal статусы, device commands, кассовые смены, фискальные чеки
- `apps.cashier` — server-rendered cashier UI на Django templates + HTMX
- `apps.ops_dashboard` — операционная панель по активной организации
- `apps.logs_dashboard` — просмотр application-логов из БД
- `apps.accounting` — бухгалтерские проводки по ключевым доменным событиям

## Технологии

- Python 3.13
- Django 6.0
- Django REST Framework
- Simple JWT
- drf-spectacular
- PostgreSQL 17
- Redis 7
- Celery 5.4
- structlog
- pytest + pytest-django
- Docker Compose

## Архитектурные ориентиры

- Основная бизнес-логика вынесена в `logic/` и `services/`, а не держится во view/serializer-слое.
- Все сущности операционного контура изолируются по `Organization`.
- Складской source of truth уже не `Product.stock_qty`, а партии и движения: `StockLot` + `StockMovement`.
- Критические сценарии оплаты, финализации и отмены защищаются транзакциями и row-level locking.
- Интеграция с физическими устройствами вынесена в outbox/pull/ack схему через `DeviceCommand`.
- Асинхронные и периодические процессы обрабатываются Celery worker/beat.

## Доменные сценарии, которые уже поддержаны

### Orders

- заказ создаётся в статусе `draft`
- позиции можно добавлять в черновик
- суммы и НДС пересчитываются на уровне заказа
- после успешного capture заказ переводится в `paid`
- история переходов пишется в `OrderStatusEvent`
- для позиций, требующих приготовления, создаются `KitchenTicket`
- есть refund и storno сценарии

### Payments and fiscal

- старт оплаты: `payments/start/`
- отдельные capture и status endpoints
- manual resolution для зависших/неоднозначных платежей
- device command pull/ack для локального агента
- health endpoints по фискальным чекам и eKasa
- кассовые смены: open / close / report
- mock fiscal flow и eKasa flow включаются через `.env`
- периодический reconciliation фискальных статусов

### Inventory and recipes

- приход товара оформляется партиями
- списание идёт по FIFO через сервисы inventory
- движения фиксируются отдельно от состояния партии
- рецептуры связывают продаваемый продукт с ингредиентами
- при продаже recipe-driven товаров склад списывается по ингредиентам

### UI and operations

- cashier login/logout и работа через сессию кассира
- открытие/закрытие смены, cash in, корзина, checkout
- kitchen board для поваров
- ops dashboard по выбранной организации
- logs dashboard с сохранением application-логов в БД

## Структура

```text
project/backend/
├── apps/
│   ├── accounting/
│   ├── cashier/
│   ├── equipment/
│   ├── inventory/
│   ├── logs_dashboard/
│   ├── ops_dashboard/
│   ├── orders/
│   ├── partners/
│   ├── payments/
│   ├── products/
│   └── recipes/
├── config/
│   ├── dictionaries/
│   ├── observability/
│   ├── orgs/
│   └── users/
├── core/
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   └── urls.py
├── tests/
├── docker-compose.yml
├── manage.py
└── requirements.txt
```

## Основные маршруты

### Service routes

- `GET /health`
- `GET /api/schema/`
- `GET /api/docs/`
- `GET /admin/`

### Auth

- `POST /api/v1/auth/login/`
- `POST /api/v1/auth/refresh/`
- `POST /api/v1/auth/logout/`
- `GET /api/v1/auth/me/`

### Dictionaries and orgs

- `GET /api/v1/dictionaries/currencies/`
- `GET /api/v1/dictionaries/countries/`
- `GET /api/v1/orgs/my/`
- `GET /api/v1/orgs/context/`
- `GET,POST /api/v1/orgs/notes/`
- `GET,POST /api/v1/orgs/members/`
- `PATCH,DELETE /api/v1/orgs/members/{id}/`
- `POST /api/v1/orgs/`

### Catalog and partners

- `GET,POST /api/v1/units/`
- `GET,PATCH,DELETE /api/v1/units/{public_id}/`
- `GET /api/v1/tax-rates/`
- `GET,POST /api/v1/partners/`
- `GET,PATCH,DELETE /api/v1/partners/{public_id}/`

### Orders and kitchen

- `GET,POST /api/v1/orders/`
- `GET,PATCH /api/v1/orders/{public_id}/`
- `GET,POST /api/v1/orders/{order_public_id}/items/`
- `GET /api/v1/orders/{public_id}/status-events/`
- `POST /api/v1/orders/{public_id}/refund/`
- `POST /api/v1/orders/{public_id}/storno/`
- `GET /api/v1/kitchen/tickets/`
- `POST /api/v1/kitchen/tickets/next/`
- `POST /api/v1/kitchen/tickets/next-with-queue/`
- `PATCH /api/v1/kitchen/tickets/{public_id}/`

### Payments and devices

- `POST /api/v1/payments/start/`
- `POST /api/v1/payments/{public_id}/capture/`
- `GET /api/v1/payments/{public_id}/status/`
- `POST /api/v1/payments/{public_id}/manual-resolution/`
- `GET /api/v1/health/fiscal-receipts/`
- `GET /api/v1/health/ekasa/`
- `GET /api/v1/device/commands/pull/`
- `POST /api/v1/device/commands/{public_id}/ack/`
- `POST /api/v1/shifts/open/`
- `POST /api/v1/shifts/{public_id}/close/`
- `GET /api/v1/shifts/{public_id}/report/`

### Cashier and dashboards

- `GET /cashier/login/`
- `GET /cashier/`
- `GET /cashier/kitchen/`
- `GET /dashboard/`
- `GET /ops/logs/`

## Переменные окружения

Шаблон: [backend/.env.example](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/.env.example)

Ключевые переменные:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `DEFAULT_CURRENCY`
- `CASHIER_DEVICE_TOKEN`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `DEVICE_COMMANDS_REDIS_URL`
- `DEVICE_COMMANDS_STREAM`
- `DEVICE_COMMANDS_STREAM_MAXLEN`
- `DEVICE_COMMANDS_RETRY_BASE_SECONDS`
- `DEVICE_COMMANDS_RETRY_MAX_SECONDS`
- `FISCAL_MOCK_ENABLED`
- `FISCAL_MOCK_OFFLINE`
- `EKASA_BASE_URL`
- `EKASA_API_KEY`
- `EKASA_TIMEOUT_S`
- `EKASA_USERNAME`
- `EKASA_PASSWORD`
- `EKASA_CASH_REGISTER_CODE`
- `EKASA_ENABLED`
- `FISCAL_RECONCILE_ENABLED`
- `LOG_LEVEL`
- `LOG_DB_ENABLED`
- `LOG_RETENTION_ENABLED`
- `LOG_RETENTION_DAYS`

## Запуск через Docker Compose

Из директории `project/backend`:

```bash
cp .env.example .env
docker compose up --build
```

Поднимаются:

- `db` — PostgreSQL
- `redis`
- `web` — Django dev server + миграции на старте
- `celery_worker`
- `celery_beat`

Приложение будет доступно на `http://localhost:8000`.

## Локальный запуск без Docker

Нужны отдельно доступные PostgreSQL и Redis.

```bash
cd project/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

Для фоновых задач:

```bash
celery -A core worker -l info -Q device_commands,default
celery -A core beat -l info
```

Для локального запуска вне Docker обычно нужно поменять в `.env`:

- `POSTGRES_HOST=127.0.0.1`
- `CELERY_BROKER_URL=redis://127.0.0.1:6379/0`
- `CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1`
- `DEVICE_COMMANDS_REDIS_URL=redis://127.0.0.1:6379/0`

## Тесты

```bash
cd project/backend
pytest
```

В репозитории уже есть широкое покрытие по:

- auth и org permissions
- orders, kitchen и статусным переходам
- payments, idempotency, manual resolution и reconciliation
- inventory и recipe-driven deduction
- cashier checkout/drafts
- eKasa/mock fiscal flow
- logging, dashboards и accounting

## Известные границы текущей реализации

- `inventory`, `recipes`, `equipment` и `accounting` присутствуют в доменной модели и логике, но не все из них пока имеют отдельный публичный REST API.
- Локальный агент устройств предполагается внешним процессом: backend только публикует команды и принимает `ack`.
- Для полноценной проверки async/fiscal flow нужен доступный Redis и настроенный `.env`.
- `Roadmap.md` описывает исходный MVP и уже отстаёт от текущего состава модулей.

## Что читать в коде

- [core/settings/base.py](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/core/settings/base.py)
- [core/urls.py](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/core/urls.py)
- [apps/orders/logic/finalize_paid_order.py](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/apps/orders/logic/finalize_paid_order.py)
- [apps/orders/logic/refund_order.py](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/apps/orders/logic/refund_order.py)
- [apps/inventory/services/receive_stock.py](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/apps/inventory/services/receive_stock.py)
- [apps/inventory/services/deduct_stock.py](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/apps/inventory/services/deduct_stock.py)
- [apps/payments/logic/start_payment.py](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/apps/payments/logic/start_payment.py)
- [apps/payments/logic/capture_payment.py](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/apps/payments/logic/capture_payment.py)
- [apps/payments/tasks.py](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/apps/payments/tasks.py)
- [apps/cashier/views.py](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/apps/cashier/views.py)
