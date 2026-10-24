# Accuracy and verification report

## Latest verification summary

Latest results reported from the project environment (2026-10-24): backend full
suite `venv\Scripts\python.exe -m pytest -q` — **70 passed**; focused vendor
suite `venv\Scripts\python.exe -m pytest tests/integration/test_vendor_compliance.py -q`
— **8 passed**; frontend TypeScript check (`tsc -b`) and production build
(`vite build`) succeeded, with the existing large-chunk warning. These results
have not been independently reproduced in the current audit environment. The
dated entries below preserve the earlier verification history.

## Supplied workbook import

The integration workflow imports the supplied September 2026 workbooks through
the same adapter, import-job, and database persistence path used by the API.
Verified first-pass and retry behavior:

| Dataset | Source rows | Imported first pass | Parser/import warnings | Rejected/failed rows | Duplicate IDs first pass | Rows counted as duplicates on retry |
|---|---:|---:|---:|---:|---:|---:|
| Gateway A payments | 475 | 475 | 0 | 0 | 0 | 475 |
| Gateway A transactions | 414 | 414 | 0 | 0 | 0 | 414 |
| Gateway A refunds | 13 | 13 | 0 | 0 | 0 | 13 |
| Gateway B balance transactions | 731 | 731 | 0 | 0 | 0 | 731 |

The zero-warning result is asserted by `backend/tests/integration/test_workflows.py`.
That test also verifies persisted payments, transactions, refunds, settlements,
source provenance, reconciliation matches/exceptions, CSV rows, and the executive
summary. Re-running a registered dataset imports no additional normalized rows;
the source identifiers are reported as duplicates on retry.

## Measurement rules and evidence limits

- Fees and taxes come from the supplied gateway exports. They are observed
  amounts, not independently verified contractual prices.
- Pricing scenarios are estimates from configured inputs. Currency, date,
  payment method, and country mismatches make the affected estimate unavailable;
  unverified pricing inputs are labeled as such.
- Money is compared and aggregated within currency. Gateway A payment amounts
  span multiple currencies while the supplied fee/tax columns are INR, so a
  blended cross-currency effective rate is not meaningful and is not reported.
- Gateway B's workbook has balance transactions associated with payout IDs but
  no independent payout-transfer ledger. Its payout totals are sums of observed
  balance rows, not a second-source payout reconciliation.
- Refund reconciliation uses the imported refund records and their statuses;
  partial refunds are cumulative by payment and currency. Failed/cancelled
  refunds are excluded from successful refund totals.

## Vendor compliance limits

- Vendor and invoice demo rows are synthetic. They demonstrate workflow and
  evidence handling; they do not establish real supplier compliance.
- Only explicitly approved, effective-dated, versioned tax rules with source
  references may drive rate-based TDS checks. Sample/unverified rules are not
  eligible for approval or calculation.
- Missing GST, PAN, tax-rule, payment, challan, or return evidence appears as an
  exception. The application does not invent legal rates, section mappings, or
  supplier evidence.
- TDS deducted, deposited through a linked challan, and reported in the return
  are treated as separate amounts. A missing challan or return remains an
  evidence gap.
- Partial payments are evaluated cumulatively against the relevant due date;
  only the unpaid balance is at risk while an invoice remains partly unpaid.

## Executed verification

On 2026-10-23, verification was run from the repository checkout:

- `backend`: `pytest -q` — 61 passed after the final importer fix.
- `frontend`: `npm run build` — TypeScript project check and production build
  succeeded. Vite reports the existing generated JavaScript chunk is larger
  than 500 kB; this is a bundle-size warning, not a failed build.
- `backend`: `python -m compileall -q app tests`, application import (44 routes),
  and `alembic upgrade head --sql` succeeded.
- Alembic `upgrade head` was applied to a clean temporary PostgreSQL 16 database;
  `alembic current` reported `91ac47bbd032 (head)`.

See the README for startup commands and environment requirements.

## Task 1 payment and settlement analysis update (2026-10-24)

### Implemented calculation behavior

- Monthly dashboard rows are grouped by transaction month, gateway, payment
  currency, fee currency, and tax currency. Captured Gateway A payment rows and
  Gateway B charge rows are used; refund rows are kept out of gross payment
  volume and remain separately available in refund reporting.
- Fees and taxes are summed separately in their imported currencies. The
  combined observed-cost figure is present only when fee/tax currencies match
  and all corresponding amounts are present. Missing amounts are counted and
  are never silently treated as zero; combined cost unavailability distinguishes
  missing amounts from currency mismatch. A missing tax currency remains
  `UNKNOWN` instead of being inferred from the fee currency. Effective fee rates are omitted if the
  gross and fee currencies differ or any fee amount is missing.
- The analytics chart includes only one user-visible currency at a time and
  only rows whose gross and fee currencies match. The detailed monthly table
  continues to show all currency combinations with explicit currency labels.
- Settlement metrics are grouped by transaction month, gateway, currency, and
  source timing basis. Gateway A uses transaction-ledger `settled_at`; Gateway
  B separately reports balance `available_on` and payout-effective timestamps.
  Average/median elapsed hours use only valid nonnegative timestamp pairs.
  Missing completion dates, negative-duration pairs, and completion timestamps
  conflicting with an explicitly unsettled flag are counted separately.
  A payout-effective or available-on date is not independent bank receipt
  evidence. No settlement SLA is inferred from these sample records.
- Existing reconciliation compares imported ledger amounts and matching
  records. It does not compare charges with contract prices because the repo has
  no independently verified contract-rate evidence. The existing settlement
  delay threshold is preserved; monthly timing metrics expose observed duration
  without asserting a contractual SLA.
- Pricing scenarios require selected pricing rules that match the requested
  gateway and do not conflict with supplied currency, geography, method, or
  effective dates. An omitted pricing-rule dimension is treated as generic
  applicability only for the estimate and is called out as a limitation.
  Outputs explicitly say estimate-only and do not produce a reliable routing recommendation. The current scenario formula applies a
  configured fixed fee once per scenario; per-transaction fixed-fee units and
  eligible transaction counts are not modeled, so scenarios containing fixed
  fees must be treated as especially limited estimates.
- The printable executive summary now includes recent monthly volume/count and
  observed fees/taxes, settlement timings, the latest reconciliation and
  exception amount-at-stake by currency, and the latest saved scenario when one
  exists. Exception amount-at-stake can overlap across flags and is not a net
  loss total.

### Current verification evidence

- `backend` — `python -m pytest -q`: **62 passed**, with one pytest-asyncio
  deprecation warning. The workflow test imports all four supplied workbooks,
  verifies row counts/warnings/retries, monthly currency behavior, settlement
  timing coverage plus missing, negative, and status-conflicting date handling,
  reconciliation, CSV, and executive-summary content.
- `frontend` — project-local TypeScript build check (`tsc -b`) and Vite
  production build both succeeded. The output retains the existing warning
  about a generated JavaScript chunk exceeding 500 kB.
- The shell `npm run build` wrapper was not usable in this environment because
  its configured global npm CLI path points to a missing `AppData\Roaming`
  install. The equivalent local `tsc` and `vite` binaries in `frontend` were
  run successfully.
- No schema or migration changes were needed for these additions. A fresh
  PostgreSQL migration was therefore not rerun for this task; the earlier
  clean-database migration evidence above remains the latest migration run.

### Remaining limits

- The supplied data is September 2026 synthetic/dummy data. Its observed costs
  and settlement timings are examples from those source rows, not current
  production performance.
- Gateway B has no separate payout-transfer/bank statement in the provided
  workbook. Payout totals and payout-effective durations remain based on that
  workbook alone.
- No signed/verified contract-rate dataset is present, so contractual charge
  comparison, confirmed savings, and reliable gateway routing recommendations
  remain unavailable.
- Fixed-fee unit semantics and a transaction count for fixed-fee scenarios are
  absent from the current pricing-rule inputs; the estimator states its
  once-per-scenario assumption and must not be used as a contract quote.

## Task 2 vendor compliance update (2026-10-24)

### Implemented and checked

- GSTR-2B matching now distinguishes a confirmed invoice mismatch from missing
  evidence. It labels an invoice `missing` only when at least one record for
  the same supplier GSTIN and return period is loaded but that invoice is not
  among them. If that supplier/period has no records, or the GSTIN is absent,
  the check creates `GST_GSTR2B_EVIDENCE_UNAVAILABLE`, records the missing
  evidence, and does not mark the check compliant.
- The synthetic demo includes a same-period unrelated invoice to demonstrate a
  confirmed GSTR-2B mismatch, and a matching row for the exact-45-day MSME case.
  Its PAN mismatch case now uses a valid PAN format that differs from the PAN
  embedded in the GSTIN. Expected outcomes in `synthetic_data.py` were adjusted
  to match actual evidence and the current risk scorecard behavior.
- An overall vendor scorecard cannot say `compliant` while it has any recorded
  exception. It is `needs_attention` when findings exist below the high-risk
  score threshold, and `high_risk` above that threshold.
- The exception API now returns `suggested_action`, and the Vendor Compliance
  page displays it with the description, amount at stake, currency, and any
  missing evidence. Scorecards and vendor master cleanup remain available via
  the existing APIs and page.
- The synthetic “short TDS” invoice is not reported as a confirmed short
  deduction: seeded rules remain unapproved samples, so the engine returns
  `TDS_RULE_UNVERIFIED` and requires an approved, effective rule. Foreign
  payment evidence remains explicitly unconfirmed; the workflow does not
  infer a legal threshold or documentation requirement from this demo.
- Tests cover TDS threshold boundaries and missing challan evidence, foreign
  vendor missing documents, MSME payment exactly on day 45, and a partially
  paid invoice whose remaining amount is reported as the amount at stake.
  They also verify all seeded vendors against `EXPECTED_OUTCOMES` and check
  scorecard, exception-report, and cleanup-list API deliverables.

### Executed verification

- `backend`: `venv\Scripts\python.exe -m pytest -q` — **70 passed**, one
  `pytest-asyncio` deprecation warning.
- `backend`: `venv\Scripts\python.exe -m pytest tests/integration/test_vendor_compliance.py -q`
  — **8 passed**, one `pytest-asyncio` deprecation warning.
- `frontend`: project-local `tsc -b` and `vite build` — both succeeded. Vite
  still reports the existing generated JavaScript chunk above 500 kB.

### Remaining limits

- Vendor, invoice, return, and challan examples are synthetic demonstration
  records, not HR-provided vendor evidence or proof of real-world compliance.
- The database has no GSTR-2B upload/period manifest. Therefore an empty
  supplier/period is safely classified as evidence unavailable; completeness
  of a purportedly loaded period cannot be independently verified by this
  application. A confirmed mismatch is limited to the available rows for that
  supplier and period.
- No tax-team-approved rule set is supplied. Sample TDS rates are not used for
  deductions, and the demo cannot confirm statutory rate/threshold/section
  applicability, PAN operative status, GST portal status, or cross-border
  documentation obligations from authoritative sources. These require review
  and evidence entered in the approved environment.
- MSME elapsed-day checks use acceptance date when recorded and invoice date as
  the documented fallback. Dispute treatment and statutory interest remain
  subject to human/legal review; the application does not calculate an
  authoritative interest liability.
