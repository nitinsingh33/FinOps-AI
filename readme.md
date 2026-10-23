# FinOps AI — Payment Reconciliation & Gateway Cost Intelligence

> **Automated payment reconciliation, exception management, and gateway cost analytics for multi-gateway payment operations.**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://reactjs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)](https://typescriptlang.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-4169E1?logo=postgresql&logoColor=white)](https://postgresql.org)

---

## Overview

**FinOps AI** is a full-stack internal platform that automates the reconciliation of payment data across multiple payment gateways. It ingests raw gateway export files (Excel/CSV), normalizes records into a unified schema, runs deterministic reconciliation across datasets, surfaces exceptions with contextual categorization, and provides analytics on gateway fees and pricing over time — all through a polished dark-themed web interface.

### Key Capabilities

| Capability | Description |
|---|---|
| **Multi-gateway ingestion** | Upload and parse Gateway A & Gateway B export formats |
| **Automated reconciliation** | Match payments against transactions, settlements, and balance reports |
| **Exception detection** | Categorize mismatches: fee discrepancies, missing settlements, duplicates, currency mismatches, and more |
| **Exception review workflow** | Triage, annotate, and resolve exceptions with audit trail |
| **Gateway cost analytics** | Track effective rates, fee trends, and per-gateway cost breakdowns |
| **Pricing intelligence** | Model and compare gateway pricing structures |
| **Report generation** | Export reconciliation summaries and exception reports |
| **AI-augmented insights** | Optional LLM integration (OpenAI / Anthropic / Google) for anomaly narratives |

---

## Architecture

```
FinOps-AI/
├── backend/                   # FastAPI Python backend
│   ├── app/
│   │   ├── api/v1/routers/    # REST endpoints (uploads, jobs, reconciliation,
│   │   │                      #   exceptions, analytics, pricing, reports, health)
│   │   ├── core/              # Configuration (Pydantic Settings v2)
│   │   ├── db/                # SQLAlchemy session & Base
│   │   ├── models/            # ORM models (PostgreSQL + JSONB)
│   │   ├── schemas/           # Pydantic request/response schemas
│   │   ├── services/          # Business logic layer
│   │   ├── utils/             # Helpers (parsing, hashing, formatting)
│   │   ├── workers/           # Celery background tasks
│   │   └── main.py            # App entry point
│   ├── alembic/               # Database migrations
│   └── requirements.txt
│
├── frontend/                  # React + TypeScript + Vite
│   └── src/
│       ├── api/               # Typed API client (TanStack Query)
│       ├── components/
│       │   ├── charts/        # Recharts-based visualizations
│       │   ├── layout/        # Sidebar, navigation shell
│       │   ├── tables/        # Data tables with sorting & filtering
│       │   └── ui/            # Reusable design-system components
│       ├── hooks/             # Custom React hooks
│       ├── pages/             # Route-level page components
│       ├── store/             # Global state (Zustand)
│       └── types/             # TypeScript interfaces
│
├── data/                      # Sample gateway export files
├── docs/                      # Extended documentation
├── scripts/                   # Utility scripts (profiling, seeding)
└── .env.example               # Environment variable template
```

### Technology Stack

**Backend**
- **FastAPI 0.115** — async REST API with automatic OpenAPI docs
- **SQLAlchemy 2.0** — async ORM with typed `Mapped` columns
- **PostgreSQL 16+** — primary store; uses `JSONB` for gateway-specific metadata
- **Alembic** — schema migrations
- **Celery + Redis** — background processing of large file imports
- **Pydantic v2 / pydantic-settings** — validation and config management
- **structlog** — structured JSON logging with request IDs
- **pandas + openpyxl** — Excel/CSV parsing and normalization

**Frontend**
- **React 18 + TypeScript** — component-driven UI
- **Vite** — fast dev server with API proxy to backend
- **TanStack Query (React Query)** — server state, caching, background refetch
- **Zustand** — lightweight global state
- **Recharts** — chart library for analytics and dashboards
- **React Router v6** — client-side routing

---

## Pages & Features

| Route | Page | Description |
|---|---|---|
| `/dashboard` | **Dashboard** | KPI cards, reconciliation summary, recent activity, gateway health |
| `/uploads` | **Uploads** | Drag-and-drop file upload, dataset type selection, import history |
| `/reconciliation` | **Reconciliation** | Run reconciliation, view run history, match statistics |
| `/exceptions` | **Exceptions** | Filtered exception list, category drill-down, review workflow |
| `/analytics` | **Analytics** | Fee trends, volume by gateway, effective rate charts |
| `/pricing` | **Pricing** | Gateway pricing models, fee-rate comparison |
| `/reports` | **Reports** | Generate & download reconciliation and exception reports |
| `/vendor-compliance` | **Vendor Compliance** | Vendor checks, scorecards, exceptions, master cleanup, and reviewed tax rules |

---

## Database Schema

```
UploadedDataset ──< ImportJob
                         │
                         ├──< GatewayAPayment
                         ├──< GatewayATransaction
                         ├──< GatewayARefund
                         └──< GatewayBBalanceRecord

ReconciliationRun ──< ReconciliationMatch
                  ──< ReconciliationException ──< ExceptionNote

GatewayPricingModel
```

**Design principles:**
- UUID primary keys on all tables
- `Decimal(20, 6)` for all monetary values — no floating-point rounding errors
- Explicit `currency` column alongside every monetary field
- `JSONB` for gateway-specific metadata that does not require relational querying
- Provenance links — every normalized record traces back to its source dataset
- Audit timestamps (`created_at`, `updated_at`) on every table

**Exception categories detected:**

| Category | Description |
|---|---|
| `missing_gateway_txn` | Payment record has no matching gateway transaction |
| `missing_payment` | Gateway transaction has no corresponding payment record |
| `unmatched_refund` | Refund cannot be linked to an original payment |
| `refund_amount_mismatch` | Refund amount differs from expected |
| `fee_discrepancy` | Gateway-charged fee deviates from contracted rate |
| `tax_discrepancy` | Tax amount does not match expected calculation |
| `net_amount_mismatch` | Net settlement differs from gross minus fees |
| `missing_settlement` | Transaction was processed but never settled |
| `unsettled_transaction` | Transaction beyond expected settlement window |
| `settlement_delay` | Settlement occurred outside SLA window |
| `duplicate_record` | Same transaction appears more than once |
| `currency_mismatch` | Currency on payment and gateway record differs |
| `ambiguous_match` | Multiple possible matches with low confidence |

---

## Quick Start

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.12+ |
| Node.js | 18+ |
| PostgreSQL | 15+ |
| Redis | 7+ (for Celery background tasks) |

### 1. Clone the Repository

```bash
git clone https://github.com/your-org/FinOps-AI.git
cd FinOps-AI
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials. At minimum, update the database connection:

```env
DATABASE_URL=postgresql+psycopg2://YOUR_USER:YOUR_PASSWORD@localhost:5432/finops_ai
ASYNC_DATABASE_URL=postgresql+asyncpg://YOUR_USER:YOUR_PASSWORD@localhost:5432/finops_ai
REDIS_URL=redis://localhost:6379/0
```

### 3. Set Up the Database

Create the PostgreSQL database and user (run as a PostgreSQL superuser):

```sql
CREATE USER finops WITH PASSWORD 'finops_secret';
CREATE DATABASE finops_ai OWNER finops;
GRANT ALL PRIVILEGES ON DATABASE finops_ai TO finops;
```

Run migrations:

```bash
cd backend
pip install -r requirements.txt
alembic upgrade head
```

The current migration head includes the initial payment/vendor schema and a
follow-up migration allowing versioned tax rules. For a clean PostgreSQL
database, create an empty database and run `alembic upgrade head` before starting
the API. The supplied workbooks can then be imported through the Uploads page or
with `python scripts/import_all.py` from `backend/`.

### 4. Start the Backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

- Swagger UI → http://localhost:8000/api/docs
- ReDoc → http://localhost:8000/api/redoc

### 5. Start the Frontend

```bash
cd frontend
npm install
npm run dev
```

Application → **http://localhost:5173**

### 6. (Optional) Start Celery Worker

Required for background processing of large file imports:

```bash
cd backend
celery -A app.workers.celery_app worker --loglevel=info
```

---

## API Reference

All endpoints are prefixed with `/api/v1`. Interactive docs at `/api/docs` when the backend is running.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/api/v1/uploads/` | Upload a gateway dataset file |
| `GET` | `/api/v1/uploads/` | List uploaded datasets |
| `GET` | `/api/v1/jobs/` | List import jobs |
| `GET` | `/api/v1/jobs/{id}` | Get import job status |
| `POST` | `/api/v1/reconciliation/runs` | Trigger a reconciliation run |
| `GET` | `/api/v1/reconciliation/runs` | List reconciliation runs |
| `GET` | `/api/v1/reconciliation/runs/{id}` | Get run details and match statistics |
| `GET` | `/api/v1/exceptions/` | List exceptions (filterable by category, status, gateway) |
| `PATCH` | `/api/v1/exceptions/{id}` | Update exception review status |
| `POST` | `/api/v1/exceptions/{id}/notes` | Add a note to an exception |
| `GET` | `/api/v1/analytics/fees` | Fee trend analytics |
| `GET` | `/api/v1/analytics/volume` | Transaction volume by gateway |
| `GET` | `/api/v1/pricing/` | List gateway pricing models |
| `GET` | `/api/v1/reports/` | List available reports |
| `POST` | `/api/v1/reports/generate` | Generate a report |
| `GET` | `/api/v1/reports/executive-summary` | One-page printable summary from persisted records |
| `POST` | `/api/v1/vendor-compliance/seed` | Load the clearly labeled synthetic vendor demo records |
| `POST` | `/api/v1/vendor-compliance/checks/run` | Assess all vendors or pass `vendor_id` |
| `GET` | `/api/v1/vendor-compliance/scorecards` | List calculated vendor scorecards |
| `GET` | `/api/v1/vendor-compliance/exceptions` | List vendor exceptions with missing evidence |
| `POST` | `/api/v1/vendor-compliance/master-cleanup/scan` | Detect vendor master quality issues |
| `GET/POST` | `/api/v1/vendor-compliance/tax-rules` | Maintain dated tax rule versions; new rules start pending review |
| `POST` | `/api/v1/vendor-compliance/tax-rules/{id}/approve` | Record explicit tax-rule approval |

Vendor Compliance setup: after migrations, open `/vendor-compliance`, choose
**Load synthetic demo data**, then **Run compliance checks**. Master-data cleanup
is a separate scan. Synthetic records are not real supplier evidence. Only
approved, effective tax rules are used for rate-based TDS checks; missing or
unverified evidence remains visible as an exception.

See [accuracy-report.md](accuracy-report.md) for verified workbook row counts,
retry behavior, measurement assumptions, and remaining evidence limits.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://finops:finops_secret@localhost:5432/finops_ai` | Sync DB connection (psycopg2) |
| `ASYNC_DATABASE_URL` | `postgresql+asyncpg://...` | Async DB connection for FastAPI |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for Celery broker |
| `SECRET_KEY` | *(change in production)* | JWT signing key |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Comma-separated allowed origins |
| `MAX_UPLOAD_SIZE_MB` | `50` | Maximum file upload size |
| `MAX_ROWS_PER_IMPORT` | `100000` | Maximum rows per imported dataset |
| `AI_ENABLED` | `false` | Enable LLM-powered insights |
| `AI_RETENTION_APPROVED` | `false` | Explicitly confirms provider and data-retention settings are approved |
| `AI_PROVIDER` | `openai` | `openai`, `anthropic`, or `google` |
| `OPENAI_API_KEY` | — | Required when `AI_PROVIDER=openai` |
| `ANTHROPIC_API_KEY` | — | Required when `AI_PROVIDER=anthropic` |
| `GOOGLE_API_KEY` | — | Required when `AI_PROVIDER=google` |
| `ENVIRONMENT` | `development` | `development` or `production` |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

---

## Development Guide

### Conventions

- **Services layer** (`app/services/`) contains all business logic — routers only validate input and delegate
- **Schemas** (`app/schemas/`) are Pydantic v2 models, strictly separate from ORM models
- **All monetary arithmetic** uses Python `Decimal`, never `float`
- **Background imports** are handled by Celery tasks, not inline in HTTP request handlers
- **Observed fees** are calculated from imported gateway records. Pricing rules and savings scenarios are configurable estimates and are not verified contract rates.
- **Compliance rules** require a source reference, version, effective dates, and explicit approval before rate-based checks use them. Legal rates and section mappings are not inferred by the application.
- External AI requests stay disabled unless `AI_ENABLED=true`, a supported provider key is present, and `AI_RETENTION_APPROVED=true`.

### Running Tests

```bash
cd backend
pytest --cov=app --cov-report=term-missing
```

### Type Checking

```bash
cd backend
mypy app/
```

### Frontend Build

```bash
cd frontend
npm run build      # Production build
npm run preview    # Preview production build locally
```

---

## Troubleshooting

### "Upload failed" / Data not inserted

The most common cause is the backend failing to connect to PostgreSQL.

**Step 1 — Verify PostgreSQL is running:**
```powershell
# Windows
Get-Service *postgres*
```

**Step 2 — Verify the database and user exist:**
```bash
psql -U postgres -c "\du"        # list users
psql -U postgres -c "\l"         # list databases
```

**Step 3 — Test the connection directly:**
```bash
psql -U finops -d finops_ai -h localhost
```
If this fails with *"password authentication failed"*, update `DATABASE_URL` in your `.env` to match the actual PostgreSQL user credentials.

**Step 4 — Run migrations** if tables are missing:
```bash
cd backend
alembic upgrade head
```

**Step 5 — Confirm the backend is reachable:**

Open http://localhost:8000/health — it should return `{"status": "ok"}`. If it doesn't, start the backend:
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

### Backend import errors on startup

```bash
cd backend
pip install -r requirements.txt
python -c "from app.main import app; print('OK')"
```

### Frontend cannot reach the API

The Vite dev server proxies `/api` to `http://localhost:8000`. If the backend port is different, update `target` in `frontend/vite.config.ts`.

---

## License

This project is proprietary and confidential. All rights reserved.

---

*Built with FastAPI · React · PostgreSQL · Celery*
