# ERP for Burger Backend

Django backend для POS / ERP-сценариев: заказы, оплаты, склад, касса, организации, фискализация и операционные панели.

## Что есть сейчас

Проект уже не ограничивается `orders/inventory core`. В текущем состоянии backend включает:

- JWT-аутентификацию и мультиорганизационность (`config.users`, `config.orgs`)
- словари и орг-справочники
- каталог товаров, вариации, add-ons, bundle-продукты
- партнёров и складские партии (`StockLot`, `StockMovement`, `StorageLocation`)
- заказы, позиции заказа, историю статусов и kitchen tickets
- платежи, capture-flow, manual resolution, fiscal receipts
- outbox/device commands, Redis stream и Celery-задачи
- cashier UI на server-render + HTMX
- ops dashboard и logs dashboard
- интеграции с mock fiscal agent и eKasa
- accounting app

## Технологии

- Python 3.13
- Django 6.0
- Django REST Framework
- PostgreSQL 17
- Redis 7
- Celery 5.4
- drf-spectacular
- pytest + pytest-django
- structlog
- Docker Compose

## Архитектурные принципы

- Бизнес-логика вынесена в use-case / logic слой, а не размазана по views и serializers.
- Критические сценарии оплаты и отмены работают внутри `transaction.atomic()`.
- Для конкурентной безопасности используются `select_for_update()` на заказах, продуктах и складских партиях.
- Склад уже партионный: списание идёт по FIFO через `StockLot`, движения фиксируются в `StockMovement`.
- Платёжные и фискальные побочные эффекты вынесены в outbox/device commands и фоновые задачи.

## Текущее поведение домена

### Orders

- заказ создаётся в статусе `draft`
- позиции можно добавлять только в `draft`
- при успешной оплате заказ переводится в `paid`
- история переходов пишется в `OrderStatusEvent`
- для требующих приготовления товаров создаются `KitchenTicket`

### Payments

- есть `payments/start/`, `capture/`, `status/`, `manual-resolution/`
- capture финализирует заказ и инициирует складские и фискальные побочные эффекты
- поддержаны статусы capture / fiscal и сценарии reconciliation

### Inventory

- приход оформляется через `receive_stock()`
- списание идёт через `deduct_stock()` по активным партиям FIFO
- остаток товара больше не хранится в `Product.stock_qty` как в старой схеме
- отображение stock в UI теперь вычисляется из активных `StockLot`

### Device Commands / Fiscal

- device commands имеют idempotency key
- есть pull/ack API для локального агента
- Celery умеет:
  - dispatch команд в Redis stream
  - mock processing
  - eKasa processing
  - reconciliation фискальных статусов
  - purge старых логов

## Важные ограничения текущей реализации

- Возврат остатков при `paid -> cancelled` на уровне партий пока не реализован. Статус заказа и связанные kitchen tickets обновляются, но обратное распределение по `StockLot` ещё не сделано.
- В кодовой базе ещё встречаются legacy-комментарии про старый `stock_qty`, но источником правды по складу уже являются партии.
- Для локального запуска тестов и фоновых задач нужен доступный PostgreSQL и, для async-флоу, Redis.

## Структура backend

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
│   └── products/
├── config/
│   ├── dictionaries/
│   ├── observability/
│   ├── orgs/
│   └── users/
├── core/
├── docker-compose.yml
├── manage.py
└── requirements.txt
```

## Основные URL

- `GET /health`
- `GET /api/schema/`
- `GET /api/docs/`
- `POST /api/v1/auth/login/`
- `POST /api/v1/payments/start/`
- `POST /api/v1/payments/{public_id}/capture/`
- `GET /api/v1/payments/{public_id}/status/`
- `POST /api/v1/payments/{public_id}/manual-resolution/`
- `GET /api/v1/device/commands/pull/`
- `POST /api/v1/device/commands/{public_id}/ack/`
- `POST /api/v1/shifts/open/`
- `POST /api/v1/shifts/{public_id}/close/`
- `GET /api/v1/shifts/{public_id}/report/`
- `GET /cashier/`
- `GET /dashboard/`
- `GET /ops/logs/`

## Переменные окружения

Базовый шаблон лежит в [`project/backend/.env.example`](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/.env.example).

Ключевые переменные:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `DEVICE_COMMANDS_REDIS_URL`
- `FISCAL_MOCK_ENABLED`
- `FISCAL_MOCK_OFFLINE`
- `EKASA_ENABLED`
- `EKASA_BASE_URL`
- `EKASA_API_KEY`
- `LOG_DB_ENABLED`

## Запуск через Docker Compose

Из директории [`project/backend`](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend):

```bash
cp .env.example .env
docker compose up --build
```

Поднимутся сервисы:

- `db` PostgreSQL
- `redis`
- `web`
- `celery_worker`
- `celery_beat`

Backend будет доступен на `http://localhost:8000`.

## Локальный запуск без Docker

Нужны отдельно запущенные PostgreSQL и Redis, а также корректный `.env`.

```bash
cd project/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Отдельно для фоновых задач:

```bash
celery -A core worker -l info -Q device_commands,default
celery -A core beat -l info
```

## Тесты

```bash
cd project/backend
pytest
```

Важно:

- тесты используют Django settings с PostgreSQL
- если `POSTGRES_HOST=db`, то запуск ожидает docker-compose сеть
- вне Docker нужно явно указать локальный хост БД, например `POSTGRES_HOST=127.0.0.1`

## Что стоит читать в первую очередь

- [`project/backend/core/settings.py`](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/core/settings.py)
- [`project/backend/core/urls.py`](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/core/urls.py)
- [`project/backend/apps/orders/logic/finalize_paid_order.py`](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/apps/orders/logic/finalize_paid_order.py)
- [`project/backend/apps/inventory/services/receive_stock.py`](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/apps/inventory/services/receive_stock.py)
- [`project/backend/apps/inventory/services/deduct_stock.py`](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/apps/inventory/services/deduct_stock.py)
- [`project/backend/apps/payments/tasks.py`](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/apps/payments/tasks.py)
- [`project/backend/apps/cashier/views.py`](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/apps/cashier/views.py)
