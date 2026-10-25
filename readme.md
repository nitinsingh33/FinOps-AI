# FinOps AI

A local portfolio application for payment operations and vendor compliance review. It imports sample payment-provider spreadsheets and invoice PDFs, runs deterministic checks, and presents findings and CSV reports in a web interface.

> **Use and accuracy:** This is a portfolio demo, not a production finance or tax system. Use dummy or masked data only. Observed fees are not verified contract rates, and missing tax evidence is not proof of compliance or a violation. See [accuracy-report.md](accuracy-report.md) for calculation rules and evidence limits.

## What the app does

### Payment Intelligence

- Import Gateway A payment, transaction, and refund workbooks and Gateway B balance rows.
- Reconcile available payment and gateway records; review matches, unmatched records, and issue flags.
- View monthly transaction counts, volume, observed fees, taxes, and settlement timing, grouped without mixing currencies.
- Configure pricing assumptions and compare estimated gateway fees.
- Review the printable executive summary and download CSV reports.

### Vendor Compliance

- Review the supplied sample invoice PDFs separately from developer test records.
- Inspect extracted fields, source documents, mapping status, and review reasons.
- Run GST, TDS, MSME, and vendor-master checks; review scorecards and exceptions.
- Download the vendor scorecard, compliance exception, vendor cleanup, and document review CSVs.
- Manage versioned tax rules. Sample rules are not approved legal rules.

The invoice PDFs do not prove registration status, GSTR-2B presence, payment, TDS deduction/deposit/reporting, or MSME status. Those findings remain evidence gaps unless the relevant records are supplied.

## Architecture

```mermaid
flowchart LR
    Browser[React and TypeScript] -->|REST API| API[FastAPI]
    API --> Services[Import, reconciliation, analytics, pricing, compliance]
    Services --> ORM[SQLAlchemy]
    ORM --> DB[(PostgreSQL)]
    API --> Files[Local upload storage]
    API -->|Background jobs| Redis[(Redis)]
    Redis --> Worker[Celery worker]
    Worker --> Services
```

The frontend calls API routes under `/api/v1`. PostgreSQL stores normalized records and results; uploaded source files are stored separately. Redis and Celery process background jobs when configured.

## Sample data

The four payment workbooks are in `data/`:

| File                                     | Upload type        | Verified source rows |
| ---------------------------------------- | ------------------ | -------------------: |
| `GatewayA_payments_Sep26_dummy.xlsx`     | `GWA_PAYMENTS`     |                  475 |
| `GatewayA_transactions_Sep26_dummy.xlsx` | `GWA_TRANSACTIONS` |                  414 |
| `GatewayA_refunds_Sep26_dummy.xlsx`      | `GWA_REFUNDS`      |                   13 |
| `GatewayB_Sep26_dummy.xlsx`              | `GWB_BALANCE`      |                  731 |

These are dummy September 2026 files. The checked import tests verify 1,633 source rows across the four files and idempotent retries; details and caveats are in [accuracy-report.md](accuracy-report.md).

The invoice sample contains 50 PDFs. The most recently recorded import parsed all 50 files, mapped 38 tax invoices, and kept all 50 in review because required external evidence is incomplete. This describes that dated sample import, not a guaranteed count for every database. The local `data/Sample_Invoices/` folder and runtime uploads are ignored by Git; do not commit supplied invoice files.

## Run locally on Windows

### Prerequisites

- Python 3.12 or newer
- Node.js 20.19+ or 22.12+
- PostgreSQL running locally
- Docker Desktop with Redis 7, if you want background imports/reconciliation through Celery

### 1. Create or choose a PostgreSQL database

You can use pgAdmin or `psql`. If you need a new local role and database, run this once in a PostgreSQL query window connected as an administrator. Choose your own local password:

```sql
CREATE ROLE finops LOGIN PASSWORD 'choose-a-local-password';
CREATE DATABASE finops_ai OWNER finops;
```

If the role or database already exists, keep using it; do not recreate it. In `backend/.env`, set `DATABASE_URL` and `ASYNC_DATABASE_URL` to your local database. For the example above:

```dotenv
DATABASE_URL=postgresql+psycopg2://finops:YOUR_PASSWORD@localhost:5432/finops_ai
ASYNC_DATABASE_URL=postgresql+asyncpg://finops:YOUR_PASSWORD@localhost:5432/finops_ai
```

URL-encode special characters in the password. Do not commit `backend/.env` or real credentials.

### 2. Install backend dependencies and apply migrations

Run from the repository root in PowerShell:

```powershell
cd backend
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item ..\.env.example .env }
notepad .env
```

If `backend/.env` already exists, keep it and edit the database URLs above. From the `backend` directory, apply migrations:

```powershell
alembic upgrade head
```

### 3. Start the backend — Terminal 1

Keep this terminal open:

```powershell
cd backend
.\venv\Scripts\Activate.ps1
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Check the API at [http://localhost:8000/health/ready](http://localhost:8000/health/ready). Interactive endpoints are at [http://localhost:8000/api/docs](http://localhost:8000/api/docs).

### 4. Start the frontend — Terminal 2

Open a second terminal at the repository root:

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open [http://localhost:5173](http://localhost:5173).

### 5. Optional: start Redis and the worker — Terminal 3

Background jobs need both Redis and the Celery worker. Start a Redis container once (if it does not already exist):

```powershell
docker run --name finops-redis -p 6379:6379 -d redis:7-alpine
```

For a container you already created, start it with `docker start finops-redis`. Then, in Terminal 3:

```powershell
cd backend
.\venv\Scripts\Activate.ps1
celery -A app.workers.celery_app worker --loglevel=info --pool=solo
```

Keep the worker terminal running while processing imports or reconciliation jobs. If Redis is unavailable, jobs may remain queued.

## First demo walkthrough

1. In **Data Uploads**, import the four workbooks above using their matching upload types. Wait for each import job to finish and review any warnings.
2. In **Reconciliation**, trigger a run. Read **Source Rows Scanned**, **Matched**, and **Unmatched** as different record/link counts. **Exceptions** are issue flags and can overlap those counts.
3. In **Analytics**, review month-wise volume, transaction count, observed fees, and settlement timing. Keep currency groups separate.
4. In **Pricing & Savings**, add clearly labelled illustrative rules and run a scenario only when both gateways have compatible rules. Estimates are not confirmed savings.
5. In **Reports**, open the executive summary and download the payment CSVs.
6. In **Vendor Compliance**, the **Supplier Invoices** dataset is selected by default. Open **Invoices** and choose **Import invoices** to add PDFs or a ZIP. Run checks, inspect exceptions and vendor cleanup, and download the three vendor CSVs plus the document review CSV.
7. Use **Use test dataset** only when you want to inspect separate developer test records. It does not combine them with Supplier Invoices.

Selectable PDF text is extracted with `pypdf`. OCR is not configured; scanned or empty PDFs require manual review. Re-imports use document hashes to avoid duplicating the same source file.

## Reports and API

The interactive API documentation lists the current endpoints and request schemas. Main route groups include:

- `/api/v1/uploads` and `/api/v1/jobs`
- `/api/v1/reconciliation/runs` and `/api/v1/exceptions`
- `/api/v1/analytics/*`
- `/api/v1/pricing-rules` and `/api/v1/savings-scenarios`
- `/api/v1/reports/*`
- `/api/v1/vendor-compliance/*`

The Vendor Compliance page provides these CSV exports for the selected dataset: vendor scorecard, compliance exception report, vendor master cleanup, and (for supplier invoice documents) document review.

## AI, security, and limitations

- Importing, reconciliation, analytics, pricing arithmetic, and compliance checks use application code; external AI is disabled by default (`AI_ENABLED=false`).
- Do not enable an AI provider unless the provider is approved and its data-retention settings have been checked. `AI_RETENTION_APPROVED` is an operator confirmation; it does not change provider retention settings.
- Never commit passwords, API keys, `.env` files, or private invoice PDFs. The app is not hardened for public deployment and has no production authentication.
- Payment workbooks are dummy data. Fees are source-observed, not signed contract pricing. Gateway B payout rows are not independently matched to a bank transfer ledger.
- Vendor findings depend on supplied invoice evidence and approved tax rules. The sample PDFs do not include all authoritative GST, payment, TDS, or MSME records needed to confirm legal compliance.
- Scanned PDFs need OCR/manual review. Cross-currency amounts are not combined.
- Pricing scenarios are estimates using configured rules. Fixed fees are applied once per scenario; transaction count is not modeled.

## Verification

Latest recorded checks in this workspace (2026-10-25):

- Backend full suite: **81 passed**.
- Focused workflow/pricing integration tests: **13 passed**.
- Frontend `npm run build`: **passed** (TypeScript and Vite production build). Vite reports a large JavaScript chunk warning; the build completes successfully.

Older verification results, migration evidence, calculation details, and known data limitations are preserved in [accuracy-report.md](accuracy-report.md).

To rerun the checks:

```powershell
cd backend
.\venv\Scripts\Activate.ps1
python -m pytest -q
```

In another terminal:

```powershell
cd frontend
npm run build
```

## Repository map

```text
backend/                 FastAPI application, models, services, migrations, tests
  app/api/v1/routers/    API endpoints
  app/services/          Import, analytics, reconciliation, pricing, compliance
  alembic/               Database migrations
data/                     Supplied dummy payment workbooks
frontend/src/             React application and pages
accuracy-report.md        Verification evidence and calculation limits
LICENCE                   Repository licence terms
```

## Licence

This repository is proprietary and all rights reserved. See [LICENCE](LICENCE).
