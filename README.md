# ERP for Burger

Django-based ERP/POS for a restaurant workflow. The backend combines REST API, server-rendered cashier and dashboard pages, asynchronous payment/fiscal tasks through Celery, and organization-scoped domain logic for orders, stock, recipes, and accounting.

## Current State

The codebase currently includes:

- JWT auth with a custom user model and `/api/v1/auth/me/`
- multitenancy through organizations, memberships, session org context, and `X-ORG-ID`
- dictionaries for currencies and countries
- catalog primitives: units and tax rates
- products, partners, equipment, inventory, recipes, and accounting models
- draft orders, order items, status history, refund/storno flows, and kitchen tickets
- payment start/capture/status flow, manual resolution, device command queue, and shifts
- mock fiscal mode, eKasa integration switches, and NEXO terminal support
- cashier UI, kitchen board, ops dashboard, and logs dashboard

Not everything above is exposed as public REST endpoints yet. Some parts currently exist as models, admin integration, services, and internal logic.

## Stack

- Python 3.13
- Django 6.0
- Django REST Framework
- SimpleJWT
- PostgreSQL
- Redis
- Celery
- drf-spectacular for Swagger/OpenAPI
- pytest + pytest-django

## Repository Layout

The repository structure is as follows:

```text
rest-erp/
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
│   │   ├── ekasa/
│   │   ├── logic/
│   │   ├── nexo/
│   │   └── providers/
│   ├── products/
│   └── recipes/
├── config/
│   ├── dictionaries/
│   ├── observability/
│   ├── orgs/
│   └── users/
├── core/
│   ├── settings/
│   ├── celery.py
│   └── urls.py
├── docs/
├── tests/
├── docker-compose.yml
├── Dockerfile
├── manage.py
├── pytest.ini
├── requirements.txt
├── .env.example
└── README.md
```

## Documentation

- [CASHIER_GUIDE.md](./docs/CASHIER_GUIDE.md)
- [OPERATIONS_GUIDE.md](./docs/OPERATIONS_GUIDE.md)
- [Roadmap.md](./docs/Roadmap.md)
- diagrams in [`docs/diagrams/`](./docs/diagrams/)
- UI screenshots in [`docs/screenshots/`](./docs/screenshots/)

## Screenshots

Main cashier screen:

![Cashier main screen](docs/screenshots/Screenshot%202026-04-10%20at%2012.20.43.png)

Cashier payment flow:

![Cashier payment flow](docs/screenshots/Screenshot%202026-04-10%20at%2013.08.28.png)

Kitchen board:

![Kitchen board](docs/screenshots/Screenshot%202026-04-11%20at%2019.45.00.png)

## Configuration

Base environment template: [`.env.example`](./.env.example)

Important variables:

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
- `DEVICE_COMMANDS_STREAM`
- `DEVICE_COMMANDS_STREAM_MAXLEN`
- `DEVICE_COMMANDS_RETRY_BASE_SECONDS`
- `DEVICE_COMMANDS_RETRY_MAX_SECONDS`
- `FISCAL_MOCK_ENABLED`
- `FISCAL_MOCK_OFFLINE`
- `EKASA_ENABLED`
- `EKASA_BASE_URL`
- `EKASA_API_KEY`
- `EKASA_TIMEOUT_S`
- `EKASA_USERNAME`
- `EKASA_PASSWORD`
- `EKASA_CASH_REGISTER_CODE`
- `FISCAL_RECONCILE_ENABLED`
- `DEFAULT_CURRENCY`
- `CASHIER_DEVICE_TOKEN`
- `LOG_LEVEL`
- `CORS_ALLOWED_ORIGINS`
- `CORS_ALLOW_CREDENTIALS`
- `CSP_REPORT_ONLY`
- `LOG_DB_ENABLED`
- `LOG_RETENTION_ENABLED`
- `LOG_RETENTION_DAYS`

Rules enforced by settings:

- `FISCAL_MOCK_ENABLED` and `EKASA_ENABLED` cannot both be `true`
- production settings require `CASHIER_DEVICE_TOKEN`
- `manage.py` defaults to `core.settings.dev`
- pytest also uses `core.settings.dev`

## Development

### Docker Development

#### Step 1: Clone and Setup

```bash
# Clone the repository
git clone https://github.com/rednaxela1813/rest-erp.git
cd rest-erp

# Copy environment template
cp .env.example .env
```

#### Step 2: Configure Environment

Use Django's built-in utility to generate a secure SECRET_KEY (run inside Docker container):

```bash
# After containers are running, generate a new secret key
docker compose exec web python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Then update your `.env` file with the generated key:

```env
DJANGO_SECRET_KEY=your-generated-secret-key-here
```

#### Step 3: Start Application

```bash
# If you have conflicting containers, clean them first:
docker compose down

# Build and start all services
docker compose up -d --build
```

This compose file starts:

- `db` - PostgreSQL 17 database
- `redis` - Redis 7 for caching and message broker
- `web` - Django application with auto-migrations
- `celery_worker` - Background task processor
- `celery_beat` - Periodic task scheduler

## Production

### Docker Production

For a production-style container run, use the dedicated compose file and env template:

```bash
cp .env.prod.example .env.prod
docker compose -f docker-compose.prod.yaml --env-file .env.prod up -d --build
```

Production-related files:

- `docker-compose.prod.yaml` - isolated production compose project
- `Dockerfile.prod` - production image with `gunicorn`
- `requirements-prod.txt` - production-only Python dependencies
- `.env.prod.example` - production environment template
- `scripts/web-entrypoint.sh` - startup script that runs migrations and `collectstatic`

This stack differs from the dev compose in a few important ways:

- uses `core.settings.prod`
- starts Django with `gunicorn` instead of `runserver`
- runs without bind mounts
- executes `migrate` and `collectstatic` on web container startup
- serves static files through WhiteNoise
- uses its own Compose project name: `rest-erp-prod`
- uses a separate application image tag: `rest-erp-prod-app:latest`

Because the production compose file is isolated under its own project name, it does not have to
share containers, volumes, or networks with the development stack.

Before first launch, update at least these values in `.env.prod`:

- `DJANGO_SECRET_KEY`
- `DJANGO_ALLOWED_HOSTS`
- `POSTGRES_PASSWORD`
- `CASHIER_DEVICE_TOKEN`

If you run Django directly on port `8000` without an external TLS terminator, keep
`DJANGO_SECURE_SSL_REDIRECT=False`. If you place the app behind Nginx/Caddy/Traefik with HTTPS,
set it to `True`.

Useful commands:

```bash
docker compose -f docker-compose.prod.yaml --env-file .env.prod logs -f web
docker compose -f docker-compose.prod.yaml --env-file .env.prod exec web python manage.py createsuperuser
docker compose -f docker-compose.prod.yaml --env-file .env.prod exec web python manage.py seed_dictionaries
docker compose -f docker-compose.prod.yaml --env-file .env.prod down
```

## Common Post-Setup

These steps apply after either the development Docker stack or the production Docker stack is up.

### Step 1: Create Superuser

```bash
# Development
docker compose exec web python manage.py createsuperuser

# Production
docker compose -f docker-compose.prod.yaml --env-file .env.prod exec web python manage.py createsuperuser
```

Follow the prompts to set username, email, and password.

### Step 2: Initialize Data

```bash
# Development
docker compose exec web python manage.py seed_dictionaries

# Production
docker compose -f docker-compose.prod.yaml --env-file .env.prod exec web python manage.py seed_dictionaries
```

### Step 3: Setup Organization (Required)

The application requires organization setup through Django admin:

1. **Access Django Admin**: Navigate to `http://localhost:8000/admin/`
2. **Login**: Use your superuser credentials
3. **Create Organization**:
   - Go to "Orgs" → "Organizations"
   - Click "Add Organization"
   - Fill in organization details (name, description, etc.)
   - Save the organization
4. **Add Organization Member**:
   - Go to "Orgs" → "Organization members"
   - Click "Add Organization member"
   - Select your superuser in the "User" field
   - Select the created organization
   - Set role to **"owner"** (important for full access)
   - Save the member

### Step 4: Verify Installation

Check that everything is working:

- **Health Check**: `http://localhost:8000/health`
- **API Documentation**: `http://localhost:8000/api/docs/`
- **Admin Panel**: `http://localhost:8000/admin/`
- **Cashier Interface**: `http://localhost:8000/cashier/`
- **Operations Dashboard**: `http://localhost:8000/dashboard/`

### Local Development Without Docker

For development without Docker:

```bash
# Setup Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Update .env with local database settings

# Run Django
python manage.py migrate
python manage.py seed_dictionaries
python manage.py createsuperuser
python manage.py runserver
```

Run background workers in separate terminals:

```bash
# Terminal 1: Celery worker
celery -A core worker -l info -Q device_commands,default

# Terminal 2: Celery beat scheduler
celery -A core beat -l info
```

## Tests

Run tests with Docker (recommended):

```bash
# Run all tests
docker compose exec web pytest

# Run specific test file
docker compose exec web pytest tests/test_health.py

# Run specific test module
docker compose exec web pytest tests/test_kitchen_tickets.py

# Run tests with specific markers
docker compose exec web pytest -m integration

# Run with verbose output
docker compose exec web pytest -v
```

Or run tests locally (requires local setup):

```bash
# From project root
pytest
pytest tests/test_health.py
pytest tests/test_kitchen_tickets.py
pytest -m integration
```

## Public Routes

### Service

- `GET /health`
- `GET /api/schema/`
- `GET /api/docs/`
- `GET /admin/`

### Auth

- `POST /api/v1/auth/login/`
- `POST /api/v1/auth/refresh/`
- `POST /api/v1/auth/logout/`
- `GET /api/v1/auth/me/`

### Dictionaries

- `GET /api/v1/dictionaries/currencies/`
- `GET /api/v1/dictionaries/countries/`

### Organizations

- `GET /api/v1/orgs/my/`
- `GET /api/v1/orgs/context/`
- `GET,POST /api/v1/orgs/notes/`
- `GET,POST /api/v1/orgs/members/`
- `PATCH,DELETE /api/v1/orgs/members/{id}/`
- `POST /api/v1/orgs/`

### Catalog

- `GET,POST /api/v1/units/`
- `GET,PATCH,DELETE /api/v1/units/{public_id}/`
- `GET /api/v1/tax-rates/`
- `GET,POST /api/v1/partners/`
- `GET,PATCH,DELETE /api/v1/partners/{public_id}/`

### Orders And Kitchen

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

### Payments, Fiscal Health, Device Commands, Shifts

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

### Server-Rendered UI

- `/cashier/login/`
- `/cashier/logout/`
- `/cashier/`
- `/cashier/session/open/`
- `/cashier/session/cash-in/`
- `/cashier/session/close/`
- `/cashier/products/`
- `/cashier/cart/`
- `/cashier/cart/add/{product_id}/`
- `/cashier/cart/add-barcode/`
- `/cashier/cart/remove/{product_id}/`
- `/cashier/cart/clear/`
- `/cashier/cart/restore/`
- `/cashier/kitchen/`
- `/cashier/kitchen/panel/`
- `/cashier/kitchen/next/`
- `/cashier/kitchen/tickets/{public_id}/`
- `/cashier/checkout/`
- `/cashier/payments/{public_id}/`
- `/cashier/payments/{public_id}/status/`
- `/cashier/payments/{public_id}/retry-fiscal/`
- `/cashier/payments/{public_id}/confirm/cash/`
- `/cashier/payments/{public_id}/confirm/card/`
- `/cashier/device/payments/{public_id}/cash/`
- `/cashier/device/payments/{public_id}/card/`
- `/cashier/drafts/{public_id}/pay/{tender}/`
- `/cashier/drafts/{public_id}/cancel/`
- `/cashier/orders/{public_id}/refund/`
- `/dashboard/`
- `/dashboard/metrics/`
- `/dashboard/select-org/`
- `/ops/logs/`

## Architecture Notes

- The project is a modular monolith with multiple Django apps and a shared PostgreSQL database.
- HTTP views, API views, and Celery tasks are kept thin where practical; business logic is intentionally pushed into focused `logic/` and `services/` modules.
- The cashier UI is server-rendered, while cart, checkout, payment confirmation, fiscalization, session, and device-callback behavior lives in `apps/cashier/logic/`.
- Inventory relies on stock lots and stock movements rather than a simple product counter.
- Payment and order-finalization flows use transactions and row-level locking.
- Device integration is organized around queued commands and async workers.
- Logging can be persisted to the database and cleaned by periodic Celery tasks.

## Known Practical Notes

- The compose file automatically runs migrations before starting the dev server.
- `seed_dictionaries` exists and should be run for a fresh local database.
- Media files are served by Django only in debug mode.
- There are generated local files like `celerybeat-schedule*`; they are runtime artifacts, not project documentation targets.

## Troubleshooting

### Container Name Conflicts

If you get "container name already in use" errors:

```bash
# Stop and remove all containers
docker compose down

# Or force remove specific containers
docker rm -f auth_redis auth_db auth_web auth_celery_worker auth_celery_beat

# Then restart
docker compose up -d --build
```

### Missing SECRET_KEY

If you get "SECRET_KEY" errors, make sure to:

1. Copy `.env.example` to `.env`
2. Generate a secure secret key after containers start:
   ```bash
   docker compose exec web python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```
3. Update `DJANGO_SECRET_KEY` in your `.env` file
4. Restart containers: `docker compose restart`

### Organization Access Issues

If you can't access cashier or dashboard interfaces:

1. Ensure you've created an organization in Django admin
2. Add your user as an organization member with "owner" role
3. The application is multi-tenant and requires proper organization setup

### Database Connection Issues

If you get database connection errors:

```bash
# Check if database container is running
docker compose ps

# View database logs
docker compose logs db

# Reset database (WARNING: destroys data)
docker compose down -v
docker compose up -d --build
```
