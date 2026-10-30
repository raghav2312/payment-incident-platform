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
- Generate request IDs and return them in X-Request-ID response headers.
- Emit JSON application logs with UTC timestamps and request context.
- Log application startup, shutdown, and application health checks.
- Log HTTP request method, path, response status, and duration in milliseconds.
- Log unhandled request exceptions with tracebacks and request IDs.
- Return generic JSON 500 responses with request IDs for unhandled errors before a response starts.
- Support an optional Idempotency-Key header for payment creation.
- Store the payment and its replay response atomically in PostgreSQL.
- Return the original creation response for matching retries.
- Reject reuse of a key with different payment details using HTTP 409.
- Handle concurrent requests using the same idempotency key.

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

Apply pending migrations to a new or existing database:

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

### Payment creation idempotency

POST /payments accepts an optional Idempotency-Key header, for example:

    Idempotency-Key: demo-payment-001

Keys must contain 1–100 characters using only letters A–Z and a–z,
digits, periods, underscores, colons, or hyphens. Keys are case-sensitive.

- A new key creates a payment and saves its creation response in one transaction.
- The same key with equivalent validated payment details returns the original
  response with HTTP 201, without creating another payment.
- The same key with different payment details returns HTTP 409.
- Different keys allow separate payments with identical details.
- Requests without a key create a new payment each time.
- Invalid keys return HTTP 422 before payment creation.

Retries return the saved creation response even if the payment's current
status has changed. Use GET /payments/{payment_id} to retrieve its current state.

Concurrent requests with the same key create only one payment. Matching
requests receive the same result; conflicting requests receive HTTP 409.

Keys currently apply globally to payment creation and do not expire.

## Automated tests

Tests use `payments_test_db`, separate from the development database.

With PostgreSQL running, create the test database once:

```powershell
docker compose exec db psql -U payments_user -d payments_db -c "CREATE DATABASE payments_test_db;"
```

Skip this command if the test database already exists.

Run the tests:

```powershell
python -m pytest tests -v
```

The test setup verifies that it targets payments_test_db and applies pending
Alembic migrations before running tests.

Most API tests override the database session dependency and roll back their
changes after each test. Concurrency tests use independent database sessions
and real commits, then delete only the records belonging to their unique
test customer and idempotency key.

The API server does not need to be running: TestClient calls the application
directly. PostgreSQL must be running.

Current checkpoint: 37 test cases passing—15 payment API cases,
15 idempotency cases, and 7 request-context/logging cases—covering:

- Payment creation and retrieval.
- Invalid amounts, currency, and blank customer references.
- Missing payment IDs and invalid UUIDs.
- Customer and status filtering.
- Pagination and query-parameter validation.
- Creation-time ordering and the payment-ID tie-breaker.
- Distinct request IDs for separate requests.
- Request-ID headers on validation-error responses.
- Matching request IDs in health-check logs and response headers.
- Request-log fields for successful responses and validation errors.
- Exception logging, error propagation, and request-context cleanup.
- Generic HTTP 500 responses with request IDs matching their error logs.
- Fingerprint normalization for equivalent payment requests.
- Matching retries, conflicting details, and separate keys.
- Replay of the original response after payment state changes.
- Invalid idempotency headers and creation without a key.
- Transaction rollback after a failed creation and successful retry.
- Concurrent requests with matching and conflicting payment details.

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
  logging_config.py  JSON log formatting and application logger setup
  middleware/
    __init__.py      Middleware package
    request_context.py Request-ID context and response headers
  routers/
    __init__.py      Router package
    payments.py     Payment creation, retrieval, and listing routes
  services/
    __init__.py      Services package
    payments.py      Payment creation, fingerprints, and idempotency
tests/
  conftest.py        Test database setup and fixtures
  test_payments.py   Payment API tests
  test_request_context.py Request-ID and logging tests
  test_idempotency.py Idempotency and concurrency tests
migrations/
  env.py            Alembic environment and model metadata
  versions/         Versioned database schema changes
alembic.ini         Alembic configuration
check_migrations.py Migration verification against a dedicated database
check_db.py          Database connectivity check
create_tables.py    Initial table creation
compose.yaml        PostgreSQL service configuration
requirements.txt    Application dependencies
requirements-dev.txt Application and test dependencies
.env.example        Configuration template
```

## Planned development

- Extend the payment service layer as processing functionality grows.
- Extend logging with payment operations.
- Add simulated processing, attempts, and payment event history.
- Add investigation SQL and incident management.
- Add CSV batch validation and reconciliation.
- Introduce Redis for a defined supporting purpose.
- Add further tests, GitHub Actions, runbooks, and demo scenarios.

The application will remain one modular FastAPI application.
PostgreSQL will remain the authoritative source of payment state.