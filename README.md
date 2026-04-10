# ERP for Burger

A monorepo for a restaurant ERP/POS built on Django. The project now covers more than a basic catalog and ordering flow: it includes organization-level data isolation, a cashier UI, payments, fiscalization, inventory, recipes, accounting entries, and internal operations dashboards.

## Repository Contents

- `backend/` — the main Django backend: REST API, cashier UI built with Django templates + HTMX, Celery tasks, and domain logic
- `docs/diagrams/` — diagrams for payment and fiscal flows
- `CASHIER_GUIDE.md` — a short cashier cheat sheet for non-standard situations
- `OPERATIONS_GUIDE.md` — operational procedures for admins during payment and fiscalization issues
- `Roadmap.md` — the historical MVP roadmap; useful as background, but it no longer reflects the current scope of the system

## Current Functional Scope

The project currently includes:

- JWT authentication, a custom user model, and `/auth/me/`
- multitenancy via `Organization`, membership roles, and org context
- system dictionaries for currencies and countries
- catalog management: units, tax rates, and products
- partners and equipment
- inventory lots and movements as the source of truth for stock
- recipes and ingredient deduction on sale
- orders, order items, status events, and kitchen tickets
- payments, capture flow, manual resolution, device commands, and cashier shifts
- mock fiscal flow and eKasa integration via Celery and Redis Stream
- cashier UI, kitchen board, ops dashboard, and logs dashboard
- accounting entries for sales, stock receipts, and stock write-offs

## Architectural Direction

- The project remains a modular monolith with a single PostgreSQL database.
- Domain logic is pushed into `logic/` and `services/` instead of staying in views.
- All operational data is isolated per organization.
- Inventory uses `StockLot` and `StockMovement` as the source of truth instead of a simple counter on the product.
- Critical payment, finalization, and cancellation flows rely on transactions and row-level locking.
- External device integration is built around an outbox/pull/ack model using Redis Stream.

## Structure

```text
project/
├── backend/
│   ├── apps/
│   ├── config/
│   ├── core/
│   ├── tests/
│   ├── docker-compose.yml
│   ├── manage.py
│   ├── requirements.txt
│   └── .env.example
├── docs/
│   ├── diagrams/
│   └── screenshots/
├── CASHIER_GUIDE.md
├── OPERATIONS_GUIDE.md
├── README.md
└── Roadmap.md
```

## Where To Start

If you need a quick orientation:

1. Review [CASHIER_GUIDE.md](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/CASHIER_GUIDE.md) and [OPERATIONS_GUIDE.md](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/OPERATIONS_GUIDE.md).
2. Open [docs/diagrams/payments_overview.svg](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/docs/diagrams/payments_overview.svg) and [docs/diagrams/payments_sequence.svg](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/docs/diagrams/payments_sequence.svg).
3. Use the sections below for backend setup, routes, and operations.

## Cashier Screenshots

Main cashier screen:

![Cashier main screen](docs/screenshots/Screenshot%202026-04-10%20at%2012.20.43.png)

Cashier menu and cart state:

![Cashier menu and cart](docs/screenshots/Screenshot%202026-04-10%20at%2012.21.02.png)

Cashier session and menu with product cards:

![Cashier product cards](docs/screenshots/Screenshot%202026-04-10%20at%2013.07.54.png)

Cashier payment flow:

![Cashier payment flow](docs/screenshots/Screenshot%202026-04-10%20at%2013.08.28.png)

Kitchen board:

![Kitchen board](docs/screenshots/Screenshot%202026-04-10%20at%2013.08.38.png)

Cashier flow with product images:

![Cashier with product images](docs/screenshots/Screenshot%202026-04-10%20at%2013.10.05.png)

## Running The Project

From `project/backend`:

```bash
cd project/backend
cp .env.example .env
docker compose up --build
```

This starts:

- `db` — PostgreSQL 17
- `redis` — Redis 7
- `web` — Django dev server; applies migrations on startup
- `celery_worker` — async task processing
- `celery_beat` — periodic scheduling

Once started:

- app: `http://localhost:8000`
- Swagger: `http://localhost:8000/api/docs/`
- healthcheck: `http://localhost:8000/health`

## Local Run Without Docker

You need PostgreSQL and Redis available separately.

```bash
cd project/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_dictionaries
python manage.py runserver
```

Background processes:

```bash
celery -A core worker -l info -Q device_commands,default
celery -A core beat -l info
```

If needed, create an admin user with:

```bash
python manage.py createsuperuser
```

## Main User Flows

### Auth and Organizations

- JWT login/refresh/logout
- `/api/v1/auth/me/` for the current user
- organization creation
- active organization selection via `X-ORG-ID`
- organization member management and org notes

### Catalog and Dictionaries

- currencies and countries
- units and tax rates
- organization-scoped products
- partners and equipment

### Inventory and Recipes

- receiving stock into lots
- FIFO deduction through inventory services
- stock movements stored separately from lot state
- recipe-driven ingredient deduction on sale

### Orders and Kitchen

- orders start as `draft`
- items can be added to drafts and recalculate totals and tax
- status changes are tracked in `OrderStatusEvent`
- `KitchenTicket` records are created for items that require preparation
- refund and storno flows are supported

### Payments and Fiscalization

- payment start, capture, and status endpoints
- manual resolution for ambiguous states
- device command pull/ack for a local agent
- mock fiscal flow and eKasa flow configured through `.env`
- health endpoints for fiscal receipts and eKasa
- cashier shifts: open, close, report
- periodic reconciliation of fiscal statuses

### UI and Operations

- cashier login/logout and cashier session flow
- shift open/close flow
- cart, checkout, and payment waiting screen
- kitchen board
- ops dashboard for the active organization
- logs dashboard backed by database-stored application logs

## HTTP Routes

### Service Routes

- `GET /health`
- `GET /api/schema/`
- `GET /api/docs/`
- `GET /admin/`

### Auth

- `POST /api/v1/auth/login/`
- `POST /api/v1/auth/refresh/`
- `POST /api/v1/auth/logout/`
- `GET /api/v1/auth/me/`

### Dictionaries and Orgs

- `GET /api/v1/dictionaries/currencies/`
- `GET /api/v1/dictionaries/countries/`
- `GET /api/v1/orgs/my/`
- `GET /api/v1/orgs/context/`
- `GET,POST /api/v1/orgs/notes/`
- `GET,POST /api/v1/orgs/members/`
- `PATCH,DELETE /api/v1/orgs/members/{id}/`
- `POST /api/v1/orgs/`

### Catalog and Partners

- `GET,POST /api/v1/units/`
- `GET,PATCH,DELETE /api/v1/units/{public_id}/`
- `GET /api/v1/tax-rates/`
- `GET,POST /api/v1/partners/`
- `GET,PATCH,DELETE /api/v1/partners/{public_id}/`

### Orders and Kitchen

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

### Payments and Devices

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

### Cashier UI and Dashboards

- `GET /cashier/login/`
- `GET /cashier/`
- `GET /cashier/session/open/`
- `GET /cashier/kitchen/`
- `GET /dashboard/`
- `GET /ops/logs/`

## Environment Variables

Template: [backend/.env.example](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/.env.example)

Required or important variables:

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

By default the project expects PostgreSQL and Redis. For local non-Docker runs, it is usually enough to switch `POSTGRES_HOST`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, and `DEVICE_COMMANDS_REDIS_URL` to `127.0.0.1`.

## Tests

Pytest is configured against `core.settings.dev`.

```bash
cd project/backend
pytest
```

The project already has broad coverage, including:

- auth, org permissions, and org context
- orders, kitchen tickets, and status transitions
- payments, idempotency, manual resolution, and reconciliation
- inventory and recipe-driven deduction
- cashier checkout and drafts
- eKasa and mock fiscal flow
- logging, dashboards, and accounting

The [tests/](/Users/alexanderkiselev/Documents/programming/django/erp_for_burger/project/backend/tests/) directory currently contains more than 300 test files.

## Background Jobs and Integrations

Celery uses `core.celery` and auto-discovers tasks from installed apps.

Periodic jobs depend on `.env` flags:

- dispatching `DeviceCommand` items to Redis Stream for all organizations
- mock device-command processing when `FISCAL_MOCK_ENABLED=true`
- eKasa command processing when `EKASA_ENABLED=true`
- fiscal status reconciliation when `FISCAL_RECONCILE_ENABLED=true`
- old log cleanup when `LOG_RETENTION_ENABLED=true`

Important: the backend is not itself the local device agent. It publishes commands and accepts `ack` calls; the actual terminal and fiscal device integration is expected to run as an external process.

## Current Boundaries

- Not every domain has a dedicated public REST API yet, even where the model and business logic are already implemented.
- Full payment and fiscal async-flow testing requires Redis, Celery worker, and Celery beat.
- `Roadmap.md` reflects only the original MVP plan and is behind the actual codebase state.

## Documentation Status

- This root `README` is now the single documentation entry point for the repository.
- `Roadmap.md` should not be used as a description of the current system state; it is an archived MVP plan.
