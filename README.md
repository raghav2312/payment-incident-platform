# Payment Processing & Incident Investigation Platform

A project  using synthetic payments to demonstrate API validation, PostgreSQL investigation, automated
testing, and eventually payment processing and incident management.

This application does not move real money or use real banking credentials.

## Current functionality

- Application and database health checks.
- Create pending payments in CAD.
- Retrieve a payment by UUID.
- List payments with customer and status filters.
- Paginate results using limit and offset.
- Order results by creation time descending, then payment ID descending.
- Validate request data and enforce database constraints.
- Run payment API tests against a separate PostgreSQL test database.

Creating a payment currently saves a pending record. It does not process
the payment.

## Technology

- Python and FastAPI
- Pydantic
- SQLAlchemy and psycopg
- PostgreSQL 16 in Docker Compose
- pytest and FastAPI TestClient

Development environment: Windows, PowerShell, and VS Code.

## Run locally

Run the following commands from the project root.

### 1. Create a virtual environment and install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` includes the application dependencies and testing tools.

### 2. Configure the environment

For a fresh checkout:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and replace the placeholder password with a local password.
Do not commit `.env`.

Default connection settings:

| Setting | Value |
|---|---|
| Database | payments_db |
| Database user | payments_user |
| Host | 127.0.0.1 |
| Windows port | 5434 |
| Container port | 5432 |
| Compose service | db |

PostgreSQL initializes its credentials when its data volume is first created.
Editing `.env` later does not automatically change an existing database password.

### 3. Start PostgreSQL

Start Docker Desktop, then run:

```powershell
docker compose up -d db
docker compose ps
```

Wait until the database service is healthy.

The `payments_data` volume preserves the database between container restarts.

### 4. Apply database migrations

For a fresh database:

```powershell
python -m alembic upgrade head
```

This applies the versioned migrations that create the database tables.

For an existing database previously created using `create_tables.py`,
verify that its schema matches the baseline before recording it with
`alembic stamp`. Stamping records a migration version without applying
its schema changes.

### 5. Start the API

```powershell
python -m uvicorn app.main:app --reload --port 8001
```

- API: http://127.0.0.1:8001
- Swagger UI: http://127.0.0.1:8001/docs

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | /health | Application health |
| GET | /health/db | Database connectivity |
| POST | /payments | Create a pending payment |
| GET | /payments/{payment_id} | Retrieve one payment |
| GET | /payments | Filter and paginate payments |

List endpoint parameters:

| Parameter | Behavior |
|---|---|
| customer_reference | Exact customer match |
| status | pending, succeeded, or failed |
| limit | 1–100; default 20 |
| offset | Zero or greater; default 0 |

Example payment request:

```json
{
  "customer_reference": "demo_customer",
  "amount": "50.00",
  "currency": "CAD"
}
```

Money uses Python Decimal and PostgreSQL Numeric.

## Automated tests

Tests use `payments_test_db`, separate from the development database.

With PostgreSQL running, create the test database once:

```powershell
docker compose exec db psql -U payments_user -d payments_db -c "CREATE DATABASE payments_test_db;"
```

Skip this command if the test database already exists.

Run the tests:

```powershell
python -m pytest tests/test_payments.py -v
```

The test setup verifies that it targets payments_test_db, applies pending
Alembic migrations, overrides the API's database session dependency,
and rolls back each test's payment changes.

The API server does not need to be running: TestClient calls the application
directly. PostgreSQL must be running.

Current checkpoint: 15 payment API tests passing, covering:

- Payment creation and retrieval.
- Invalid amounts, currency, and blank customer references.
- Missing payment IDs and invalid UUIDs.
- Customer and status filtering.
- Pagination and query-parameter validation.
- Creation-time ordering and the payment-ID tie-breaker.

The current dependency combination emits a TestClient deprecation warning
about httpx. Tests pass; dependency compatibility cleanup remains pending.

## Project structure

```text
app/
  config.py          Environment settings
  database.py        SQLAlchemy engine
  dependencies.py    Per-request database session
  models.py          Database models and constraints
  schemas.py         Request and response validation
  main.py            FastAPI setup, router registration, and health routes
  routers/
    __init__.py      Router package
    payments.py     Payment creation, retrieval, and listing routes
tests/
  conftest.py        Test database setup and fixtures
  test_payments.py   Payment API tests
check_db.py          Database connectivity check
create_tables.py    Initial table creation
compose.yaml        PostgreSQL service configuration
requirements.txt    Application dependencies
requirements-dev.txt Application and test dependencies
.env.example        Configuration template
```

## Planned development

- Extract payment business logic into services as functionality grows.
- Add structured JSON logs and request IDs.
- Implement durable PostgreSQL-backed idempotency.
- Add simulated processing, attempts, and payment event history.
- Add investigation SQL and incident management.
- Add CSV batch validation and reconciliation.
- Introduce Redis for a defined supporting purpose.
- Add further tests, GitHub Actions, runbooks, and demo scenarios.

The application will remain one modular FastAPI application.
PostgreSQL will remain the authoritative source of payment state.