# FinLedger: Banking Ledger & Money Transfer API

[![CI](https://github.com/vishant0815/finledger-banking-api/actions/workflows/ci.yml/badge.svg)](https://github.com/vishant0815/finledger-banking-api/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-336791)

A production-style fintech backend: a **double-entry ledger** with **atomic, idempotent money
transfers** that stay correct under concurrent load.

The project is built in small, tested milestones. Its goal is to prove guarantees that matter
in real payment systems:

- Every posted journal entry balances to zero.
- 100 simultaneous transfers cannot overspend the same account.
- Retrying a transfer with the same idempotency key never charges the sender twice.
- Money is never represented as a float.

## Tech stack

| Area | Tools |
| --- | --- |
| API | Python 3.12+, FastAPI, Pydantic v2 |
| Database | PostgreSQL, SQLAlchemy 2.0 (async), asyncpg, Alembic |
| Messaging & cache | Apache Kafka *(Phase 9)*, Redis *(Phase 10)* |
| Auth | JWT *(Phase 3)* |
| Quality | pytest, pytest-asyncio, httpx, Ruff, mypy (strict) |
| Delivery | Docker, Docker Compose, GitHub Actions |

## Roadmap

| # | Milestone | Status |
| --- | --- | --- |
| 1 | Project setup: FastAPI, config, logging, errors, Docker, CI | ✅ Done |
| 2 | Database design: accounts, journals, postings, migrations | ✅ Done |
| 3 | Authentication: JWT, registration, access control | ⏳ Next |
| 4 | Account management | |
| 5 | Double-entry ledger | |
| 6 | Money transfers: atomic, insufficient-funds checks | |
| 7 | Idempotency keys | |
| 8 | Concurrency control: row locking, race-condition tests | |
| 9 | Event-driven architecture: transactional outbox, Kafka | |
| 10 | Fraud detection rules & Redis rate limiting | |
| 11 | Integration, load, failure and security testing | |
| 12 | CI/CD, monitoring, documentation | |

## Quick start (Docker)

Requires Docker with the Compose plugin.

```bash
git clone https://github.com/vishant0815/finledger-banking-api.git
cd finledger-banking-api
cp .env.example .env          # then set POSTGRES_PASSWORD
docker compose up --build      # starts PostgreSQL, applies migrations, then starts the API
```

| URL | What |
| --- | --- |
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/api/v1/health | Liveness check |
| http://localhost:8000/api/v1/health/ready | Readiness check (includes PostgreSQL) |

## Local development

Requires [uv](https://docs.astral.sh/uv/) and a PostgreSQL instance. The easiest way to get
one is to start only the database container.

```bash
uv sync                                   # create .venv and install locked dependencies
cp .env.example .env                      # then set POSTGRES_PASSWORD
docker compose up -d db                   # PostgreSQL on localhost:5432
uv run alembic upgrade head               # apply database migrations
uv run uvicorn app.main:create_app --factory --reload
```

### Quality checks

These run in CI on every push and pull request.

```bash
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
uv run mypy                    # strict type checking
uv run pytest --cov            # unit + PostgreSQL integration tests
uv run pytest -m "not integration"   # unit tests only, no database needed
```

Integration tests create a throwaway `finledger_test` database, migrate it with Alembic and
run against the real schema. Locally they are skipped if PostgreSQL isn't running; in CI they
run against a PostgreSQL service container and can never be skipped. No Kafka or Redis needed.

### Migrations

```bash
uv run alembic revision --autogenerate -m "describe change"   # after changing models
uv run alembic upgrade head                                   # apply
uv run alembic downgrade -1                                   # roll back one step
```

A test fails if the models and migrations ever drift apart, and another runs a full
downgrade-then-upgrade round trip.

## Ledger data model

```mermaid
erDiagram
    accounts ||--o{ postings : "is credited/debited by"
    journal_entries ||--|{ postings : "has 2+ legs"

    accounts {
        uuid id PK
        varchar name
        varchar type "customer | system"
        varchar status "active | frozen | closed"
        char3 currency "ISO 4217"
        numeric balance "maintained by trigger"
    }
    journal_entries {
        uuid id PK
        varchar entry_type "deposit | withdrawal | transfer | reversal"
        char3 currency
        varchar description
        timestamptz created_at
    }
    postings {
        uuid id PK
        uuid journal_entry_id FK
        uuid account_id FK
        char3 currency
        numeric amount "signed, never zero"
        timestamptz created_at
    }
```

A **journal entry** is one financial event, for example "Alice pays Bob £30". Each **posting**
is one leg of it against one account. Amounts are signed (positive increases a balance), and
every entry's postings sum to zero, so money is only ever moved, never created. Deposits and
withdrawals balance against a `system` settlement account.

| Transfer £30 from Alice to Bob | account | amount |
| --- | --- | --- |
| posting 1 | Alice | −30.00 |
| posting 2 | Bob | +30.00 |
| **sum** | | **0.00** |

### Rules enforced by PostgreSQL itself

These hold even if application code has a bug. Each one has an integration test that bypasses
the application and tries to break it.

| Rule | How |
| --- | --- |
| Every entry balances (≥ 2 postings, sum = 0) | Deferred constraint triggers, checked at `COMMIT` |
| Ledger is append-only | Triggers reject `UPDATE`/`DELETE` on entries and postings; fix mistakes with a reversal |
| Balances can't drift from the ledger | Trigger applies each posting to `accounts.balance`; direct balance writes are rejected |
| Customer accounts can't go negative | `CHECK (type = 'system' OR balance >= 0)` on the running balance |
| No cross-currency postings | Composite foreign keys: posting currency = account currency = entry currency |
| Money is exact | `NUMERIC(19,4)` end-to-end with Python `Decimal`; floats are never used |
| Concurrent postings to one account serialise | The balance trigger's `UPDATE` takes a row lock; the CHECK sees the latest balance |

Violations surface as named constraints (`journal_entry_balanced`, `ledger_append_only`,
`balance_managed_by_ledger`, …), so the API layer can map them to precise error responses.

## API

All endpoints are versioned under `/api/v1`.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Liveness: the process is up (no external calls) |
| `GET` | `/api/v1/health/ready` | Readiness: `200` if PostgreSQL responds, otherwise `503` |

Example:

```json
GET /api/v1/health
{
  "status": "ok",
  "service": "FinLedger API",
  "version": "0.1.0",
  "environment": "local",
  "timestamp": "2026-11-23T16:45:00.000000Z"
}
```

Every error uses one envelope, and every response carries an `X-Request-ID` header:

```json
{
  "error": {
    "code": "not_found",
    "message": "Not Found",
    "request_id": "9f1c2b7e0d4a4e5f8a6b3c2d1e0f9a8b"
  }
}
```

## Configuration

Settings are read from environment variables (or `.env`) via `pydantic-settings`.
See [`.env.example`](.env.example).

| Variable | Default | Notes |
| --- | --- | --- |
| `ENVIRONMENT` | `local` | `local`, `test`, `staging`, `production` (docs are disabled in production) |
| `LOG_LEVEL` | `INFO` | |
| `LOG_JSON` | `false` | JSON logs for staging/production |
| `POSTGRES_HOST` / `POSTGRES_PORT` | `localhost` / `5432` | |
| `POSTGRES_USER` / `POSTGRES_DB` | `finledger` | |
| `POSTGRES_PASSWORD` | *(required)* | No default. The app refuses to start without it. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `10` | SQLAlchemy connection pool |

## Project structure

```
app/
├── main.py                 # application factory + lifespan (DB engine setup/teardown)
├── api/
│   ├── deps.py             # shared dependencies (settings, DB session)
│   └── v1/
│       ├── router.py       # /api/v1 router
│       └── endpoints/
│           └── health.py   # liveness & readiness
├── core/
│   ├── config.py           # pydantic-settings configuration
│   ├── logging.py          # structlog setup (console locally, JSON in prod)
│   ├── middleware.py       # request IDs + structured access log
│   └── exceptions.py       # domain errors + centralised handlers
├── db/
│   ├── base.py             # declarative base, naming conventions, money type
│   └── session.py          # async engine, session factory, DB ping
├── models/                 # SQLAlchemy models: Account, JournalEntry, Posting
└── schemas/                # Pydantic response models
migrations/                 # Alembic (async); versions/ holds schema + ledger triggers
tests/
├── api/                    # HTTP-level tests
├── unit/                   # config and DB helper tests
└── integration/            # real PostgreSQL: ledger rules + migration checks
```

## Design notes

- **Application factory + lifespan.** The DB engine is created on startup and disposed on
  shutdown. Nothing connects at import time, and every test app gets an isolated instance.
- **Liveness vs readiness.** `/health` never touches dependencies, so an orchestrator won't
  restart a healthy process because the database blipped. `/health/ready` reports `503` so
  traffic is withheld instead.
- **Request tracing.** A pure ASGI middleware assigns or propagates `X-Request-ID`, binds it to
  every log line, and logs method, path, status and duration once per request. Client-supplied
  IDs are validated to prevent log injection.
- **Safe errors.** Unexpected exceptions are logged with a traceback but return a generic
  message. Validation errors never echo submitted values back to the client.
- **Secrets.** Credentials come only from the environment, `POSTGRES_PASSWORD` has no default,
  and the database URL is masked in logs.
