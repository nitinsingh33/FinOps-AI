# FinOps AI

FinOps AI is a demo full-stack finance operations application for payment reconciliation, gateway fee analysis, savings scenarios, and vendor GST/TDS compliance workflows. It is built around masked or synthetic data and deterministic rules; AI-assisted exception explanations are optional.

> **Project status:** Core upload, reconciliation, analytics, pricing-scenario, reporting, and vendor-compliance workflows exist. See [Known limitations](#known-limitations) and [accuracy-report.md](accuracy-report.md) before treating outputs as operational or legal conclusions.

## Contents

- [Problem statement](#problem-statement)
- [What the application does](#what-the-application-does)
- [Architecture](#architecture)
- [How the workflows work](#how-the-workflows-work)
- [AI and automation](#ai-and-automation)
- [Technology](#technology)
- [Run locally on Windows](#run-locally-on-windows)
- [Demo walkthrough](#demo-walkthrough)
- [API and documentation](#api-and-documentation)
- [Tests and build](#tests-and-build)
- [Security and data handling](#security-and-data-handling)
- [Known limitations](#known-limitations)
- [Repository map](#repository-map)
- [Licence](#licence)

## Problem statement

Payment operations teams receive separate exports from payment providers. Matching those records by hand makes it harder to find missing transactions, fee or currency differences, refunds, delayed settlements, and payout issues before closing the books. Gateway fee comparisons can also be misleading when currencies or payment methods are mixed, or when observed fees are mistaken for signed contract rates.

A related vendor-compliance workflow demonstrates how GST, TDS, MSME deadlines, and vendor-master evidence can be checked and exceptions surfaced before close. Missing documents or unapproved tax rules must remain visible as gaps rather than being treated as proof of compliance.

This project provides a reviewable demo of those workflows using the supplied dummy payment workbooks and synthetic vendor records.

## What the application does

### Payment Intelligence

| Workflow | What it does | Where to find it |
|---|---|---|
| Operational overview | Shows payment/import totals, recent reconciliation runs, and recent exceptions from the API | **Dashboard** |
| Dataset import | Accepts Excel/CSV gateway exports, records import jobs, validates and normalizes rows, and preserves source provenance | **Data Uploads** |
| Reconciliation | Matches Gateway A payment and transaction records; checks unmatched records, currencies, fees, net amounts, refunds, settlements, and Gateway B balance/payout fields | **Reconciliation** |
| Exception review | Lists issue flags with severity, source links, available amounts/differences, review status, notes, and audit history | **Exceptions** |
| Monthly cost view | Groups captured Gateway A payments and Gateway B charge rows by transaction month, gateway, and currency; shows count, gross volume, observed fees, and a comparable rate where possible | **Analytics** |
| Pricing scenarios | Estimates fees using explicitly configured pricing assumptions, scoped to currency and optionally country/payment method | **Pricing & Savings** |
| Exports and summary | Provides payment, transaction, refund, and exception CSV exports plus a printable one-page executive summary | **Reports** |

### Vendor GST/TDS Compliance

The Vendor Compliance page uses synthetic example records to demonstrate vendor scorecards, exceptions, missing-evidence visibility, master-data cleanup findings, and versioned/effective-dated tax rules with explicit approval status. Compliance outcomes depend on available evidence and configured rules.

The application does not invent statutory rates or legal section mappings. The synthetic vendor records are not evidence about a real supplier.

## Architecture

```mermaid
flowchart LR
    Browser[React + TypeScript UI] -->|REST /api/v1| API[FastAPI]
    API --> Services[Import, reconciliation, analytics, pricing, reports, compliance]
    Services --> ORM[SQLAlchemy]
    ORM --> DB[(PostgreSQL)]
    API -->|queued import/reconciliation work| Redis[(Redis broker)]
    Redis --> Worker[Celery worker]
    Worker --> Services
    API -. optional exception explanation .-> AI[Configured AI provider]
    Uploads[Excel / CSV files] --> API
    API --> Storage[backend/data/uploads]
    Storage --> Services
```

The API and Celery worker share the database configuration and application services. Redis is used for asynchronous jobs. If the worker/broker is unavailable, some API paths attempt a synchronous fallback; for reliable background processing, keep Redis and the worker running.

Reconciliation values are calculated from normalized database records. The UI reads API responses; dashboard totals are not intended to be hardcoded demo metrics. Uploaded files are retained separately from normalized database rows.

## How the workflows work

### Import and reconciliation

1. Upload the supplied workbook and select its dataset type.
2. The import job parses source rows, records warnings/errors/duplicates, and saves normalized rows with source provenance.
3. Trigger a reconciliation run.
4. Review **Matches** and **Exceptions** for that run. Exceptions are issue flags and may overlap matched or unmatched records.

The supplied September 2026 workbooks are:

| Workbook | Dataset | Rows verified |
|---|---|---:|
| `GatewayA_payments_Sep26_dummy.xlsx` | Gateway A payments | 475 |
| `GatewayA_transactions_Sep26_dummy.xlsx` | Gateway A transactions | 414 |
| `GatewayA_refunds_Sep26_dummy.xlsx` | Gateway A refunds | 13 |
| `GatewayB_Sep26_dummy.xlsx` | Gateway B balance transactions | 731 |

These counts total **1,633 source rows**. They are not expected to equal the sum of matched, unmatched, and exception counts:

- **Source Rows Scanned** counts imported ledger rows included by the run.
- **Matched** counts linked Gateway A payment/transaction pairs.
- **Unmatched** counts records missing a corresponding side.
- **Exceptions** counts issue flags; multiple flags can relate to the same record, and flags can overlap matched or unmatched records.

See [accuracy-report.md](accuracy-report.md) for import warnings, retry behavior, matching assumptions, and verification history.

### Monthly metrics and observed fees

Analytics groups records by their transaction timestamp, gateway, and currency. It does not add amounts across currencies. The monthly view uses captured Gateway A payments and Gateway B charge rows; records without a transaction timestamp are omitted and the UI reports that omission.

Fees from uploaded exports are **observed fees**, not verified contract terms. If fee currency differs from transaction currency, a blended effective fee rate is not calculated.

### Pricing and savings scenarios

Pricing rules are entered by the user; newly added rules default to **Illustrative**. A scenario estimates fees for a volume using the selected rules and context. If a rule's currency, country, payment method, effective date, or fixed-fee currency does not fit the scenario, that estimate is left unavailable and the limitation is shown.

The repository does not preload made-up contract rates. Scenario output is an estimate—not guaranteed savings, a recommendation backed by a signed contract, or an independently verified quote. Use only approved pricing evidence for business decisions.

### Executive report

The **Reports** page links to a printable executive summary generated from persisted database records. It also provides CSV exports. Review the report's currency and evidence notes before sharing it.

## AI and automation

- Import normalization, reconciliation matching, metric aggregation, pricing arithmetic, and vendor checks are deterministic application code.
- AI is **disabled by default** (`AI_ENABLED=false`). When unavailable, exception investigation returns a clearly labeled deterministic fallback.
- Implemented live AI provider calls are OpenAI and Anthropic. Provider credentials are never committed to the repository.
- To enable an AI provider, the operator must set `AI_ENABLED=true`, configure the matching key, and explicitly set `AI_RETENTION_APPROVED=true`. That flag is an operator confirmation; it does not configure retention at the provider. Confirm the selected provider's retention settings separately before sending any data.
- Exception evidence packets omit customer email, phone, and card details. AI output is labeled and schema-validated; it does not update financial records, mark payments settled, or decide compliance.
- Do not send real financial or vendor data through an unapproved provider or environment.

## Technology

| Area | Main components |
|---|---|
| Backend API | Python, FastAPI, Pydantic Settings |
| Database and migrations | PostgreSQL, SQLAlchemy 2, Alembic |
| Background jobs | Celery, Redis |
| Workbook ingestion | pandas, openpyxl, xlrd |
| Frontend | React 19, TypeScript, Vite |
| Data fetching and charts | TanStack Query, Recharts |
| Optional AI investigation | OpenAI or Anthropic SDKs, disabled unless explicitly enabled |

Pinned backend dependencies are in [backend/requirements.txt](backend/requirements.txt); frontend dependencies/scripts are in [frontend/package.json](frontend/package.json).

## Run locally on Windows

### Prerequisites

- Python 3.12 or newer
- Node.js 20.19+ or 22.12+ (Vite 8 requirement)
- PostgreSQL running locally
- Redis 7+ and Docker only if you want background jobs through Celery

### 1. Prepare PostgreSQL

Create a local database and user in pgAdmin or `psql`. For example, in a PostgreSQL query window:

```sql
CREATE USER finops WITH PASSWORD 'choose-a-local-password';
CREATE DATABASE finops_ai OWNER finops;
```

Use your own local password. In `backend/.env`, set `DATABASE_URL` to match your PostgreSQL username, password, host, port, and database. For the example above:

```dotenv
DATABASE_URL=postgresql+psycopg2://finops:YOUR_URL_ENCODED_PASSWORD@localhost:5432/finops_ai
```

If a `backend/.env` already exists, edit it; do not overwrite it. The root `.env.example` is a template. Keep `.env` files and credentials private.

### 2. Install backend dependencies and migrate

Open a VS Code terminal at the repository root and run:

```powershell
cd backend
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
alembic upgrade head
```

If PowerShell blocks environment activation, run `.\venv\Scripts\alembic.exe upgrade head`. The `alembic upgrade head` command works after the environment is activated.

### 3. Start the API

Keep this terminal open:

```powershell
cd backend
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

API health: <http://localhost:8000/health/ready>
Interactive API docs: <http://localhost:8000/api/docs>

### 4. Start the frontend

Open a second VS Code terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

### 5. Optional: start Redis and the Celery worker

For background import/reconciliation tasks, start Redis. If Docker is installed and port `6379` is free:

```powershell
docker run --name finops-redis -p 6379:6379 -d redis:7-alpine
```

If that container already exists, use `docker start finops-redis`. Then open another terminal:

```powershell
cd backend
.\venv\Scripts\Activate.ps1
celery -A app.workers.celery_app worker --loglevel=info --pool=solo
```

Keep this worker terminal running. When Redis/Celery is not configured, queued jobs may not be processed until the synchronous fallback runs; for a dependable demo, start Redis and the worker before uploading files.

### 6. Load the demo data

In the app, go to **Data Uploads** and upload each workbook listed above using the matching dataset type. Wait for each import status to become `COMPLETED` (or inspect warnings if it completes with warnings). Then go to **Reconciliation** and trigger a run.

The original supplied workbooks are under `data/`. Uploading through the UI stores copies under `backend/data/uploads/` and imports their rows into PostgreSQL.

## Demo walkthrough

1. **Data Uploads:** show the four dataset imports and their job status.
2. **Reconciliation:** run/select a reconciliation; explain source rows, matched pairs, unmatched records, and overlapping exception flags.
3. **Exceptions:** open a finding and review the source evidence, available amount difference, and status.
4. **Analytics:** show month-wise volume/count/observed fees. Explain that rates are currency-specific and fees are observed.
5. **Pricing & Savings:** add two explicitly illustrative rules based on documented assumptions, then run a scenario with the same currency/geography/payment method. Present output as an estimate, not verified savings.
6. **Reports:** open the one-page summary and export CSVs as needed.
7. **Vendor Compliance:** seed synthetic demo records, run checks, and inspect scorecards, exceptions, missing evidence, cleanup findings, and tax-rule approval status.

## API and documentation

All application routes are under `/api/v1`, except health and documentation routes. The authoritative endpoint list is in the running OpenAPI page at <http://localhost:8000/api/docs>.

Main route groups include:

- `/uploads`, `/jobs`
- `/reconciliation/runs`
- `/exceptions`
- `/analytics/overview`, `/analytics/gateway-costs`, `/analytics/settlements`
- `/pricing-rules`, `/savings-scenarios`
- `/reports/executive-summary` and CSV download endpoints
- `/vendor-compliance/vendors`, `/seed`, `/checks/run`, `/scorecards`, `/exceptions`, `/master-cleanup`, `/tax-rules`

## Tests and build

From the repository root in PowerShell:

```powershell
cd backend
pytest -q
```

Frontend type-check and production build:

```powershell
cd frontend
npm run build
```

A successful Vite build may still print a bundle-size warning; that warning is distinct from a failed build. For verified import row counts, accuracy constraints, prior clean PostgreSQL migration evidence, and other caveats, see [accuracy-report.md](accuracy-report.md).

### Latest executed verification

On 2026-10-24, the backend workflow integration suite was reported with **6 passed**; this is the workflow integration test count, not the full backend test-suite count. The latest reported full-suite result was **70 passed**, with the focused vendor compliance suite at **8 passed**. The frontend TypeScript project check and Vite production build also passed; Vite printed a large-chunk size warning. The clean PostgreSQL migration verification documented in [accuracy-report.md](accuracy-report.md) was executed on 2026-10-23. These results were reported from the project environment and have not been independently reproduced in the current audit environment. See [accuracy-report.md](accuracy-report.md) for the complete verification history.

## Security and data handling

- Never commit `.env`, passwords, API keys, or real financial/vendor records.
- Use only masked or dummy data for this demo. Use real data only in an approved environment.
- Keep AI disabled unless both the provider and retention settings are approved by the responsible organization.
- Uploads are stored locally under `backend/data/uploads/`; protect and remove them according to the environment's data-handling policy.
- This project is a demonstration, not a substitute for finance, tax, legal, or compliance review.

## Known limitations

- The supplied payment workbooks are dummy September 2026 datasets, not live provider feeds or bank statements.
- Gateway B payout totals are derived from imported balance rows grouped by payout ID. The supplied workbook does not include an independent bank transfer ledger for second-source settlement verification.
- Actual observed gateway fees are not signed or independently verified contract rates. Savings estimates require user-configured pricing rules and are not guaranteed.
- The application exposes reconciliation issue flags, but a flagged exception is not proof of fraud, overcharge, or root cause.
- Vendor checks use synthetic records. Rule-based outcomes depend on evidence fields and approved rule configuration; legal interpretation requires qualified review.
- The app does not provide authentication or production deployment hardening. Do not expose a local development server to untrusted networks.
- The build has a known large JavaScript bundle warning; the production build still completes.

## Repository map

```text
FinOps-AI/
├── backend/
│   ├── app/
│   │   ├── api/v1/routers/       # FastAPI route groups
│   │   ├── core/                 # Settings and configuration
│   │   ├── db/                   # SQLAlchemy engine/session
│   │   ├── models/               # Payment and vendor ORM models
│   │   ├── services/             # Imports, analytics, reconciliation, compliance
│   │   ├── workers/              # Celery app and tasks
│   │   └── main.py               # FastAPI application
│   ├── alembic/                  # Database migration history
│   ├── data/uploads/             # Runtime upload storage (ignored by Git)
│   ├── tests/                    # Unit and integration tests
│   └── requirements.txt
├── data/                         # Supplied dummy Excel workbooks
├── frontend/
│   ├── src/api/                  # HTTP client
│   ├── src/components/layout/    # App layout and navigation
│   ├── src/pages/                # Dashboard and workflow screens
│   └── src/types/                # Frontend types
├── accuracy-report.md            # Verification evidence and limits
├── readme.md
└── .env.example
```

## Licence

This repository is proprietary and all rights reserved. See [LICENCE](LICENCE). It is not presented as an open-source licensed project.
