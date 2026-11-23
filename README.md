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
| Database | PostgreSQL, SQLAlchemy 2.0 (async), asyncpg, Alembic *(Phase 2)* |
| Messaging & cache | Apache Kafka *(Phase 9)*, Redis *(Phase 10)* |
| Auth | JWT *(Phase 3)* |
| Quality | pytest, pytest-asyncio, httpx, Ruff, mypy (strict) |
| Delivery | Docker, Docker Compose, GitHub Actions |

## Roadmap

| # | Milestone | Status |
| --- | --- | --- |
| 1 | Project setup: FastAPI, config, logging, errors, Docker, CI | ✅ Done |
| 2 | Database design: accounts, journals, postings, migrations | ⏳ Next |
| 3 | Authentication: JWT, registration, access control | |
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
docker compose up --build
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
uv run uvicorn app.main:create_app --factory --reload
```

### Quality checks

These run in CI on every push and pull request.

```bash
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
uv run mypy                    # strict type checking
uv run pytest --cov            # tests + coverage
```

The test suite needs **no** running PostgreSQL, Kafka or Redis.

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
│   └── session.py          # async engine, session factory, DB ping
└── schemas/                # Pydantic response models
tests/
├── api/                    # HTTP-level tests
└── unit/                   # config and DB helper tests
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
