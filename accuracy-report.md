# Accuracy and verification report

## Latest verification summary

The latest results recorded for the project environment on 2026-10-25 were: backend full suite, 81
passed; focused workflow/pricing integration tests, 13 passed; and frontend `npm run build`, passed
(TypeScript and Vite production build). Vite reported its existing large JavaScript bundle warning.

These are results reported from the project environment and were not independently reproduced in the
current documentation-only audit. Earlier dated results remain in the historical sections below; see
“Executed verification” and the task-specific verification sections for their original commands and
context.

## Supplied workbook import

The integration workflow imports the supplied September 2026 workbooks through the same adapter,
import-job, and database persistence path used by the API. Verified first-pass and retry behavior:

| Dataset                        | Source rows | Imported first pass | Parser/import warnings | Rejected/failed rows | Duplicate IDs first pass | Rows counted as duplicates on retry |
| ------------------------------ | ----------: | ------------------: | ---------------------: | -------------------: | -----------------------: | ----------------------------------: |
| Gateway A payments             |         475 |                 475 |                      0 |                    0 |                        0 |                                 475 |
| Gateway A transactions         |         414 |                 414 |                      0 |                    0 |                        0 |                                 414 |
| Gateway A refunds              |          13 |                  13 |                      0 |                    0 |                        0 |                                  13 |
| Gateway B balance transactions |         731 |                 731 |                      0 |                    0 |                        0 |                                 731 |

The zero-warning result is asserted by `backend/tests/integration/test_workflows.py`. That test also
verifies persisted payments, transactions, refunds, settlements, source provenance, reconciliation
matches/exceptions, CSV rows, and the executive summary. Re-running a registered dataset imports no
additional normalized rows; the source identifiers are reported as duplicates on retry.

## Measurement rules and evidence limits

- Fees and taxes come from the supplied gateway exports. They are observed amounts, not
  independently verified contractual prices.

- Pricing scenarios are estimates from configured inputs. Currency, date, payment method, and
  country mismatches make the affected estimate unavailable; unverified pricing inputs are labeled
  as such.

- Money is compared and aggregated within currency. Gateway A payment amounts span multiple
  currencies while the supplied fee/tax columns are INR, so a blended cross-currency effective rate
  is not meaningful and is not reported.

- Gateway B's workbook has balance transactions associated with payout IDs but no independent
  payout-transfer ledger. Its payout totals are sums of observed balance rows, not a second-source
  payout reconciliation.

- Refund reconciliation uses the imported refund records and their statuses; partial refunds are
  cumulative by payment and currency. Failed/cancelled refunds are excluded from successful refund
  totals.

## Vendor compliance limits

- Vendor and invoice demo rows are synthetic. They demonstrate workflow and evidence handling; they
  do not establish real supplier compliance.

- Only explicitly approved, effective-dated, versioned tax rules with source references may drive
  rate-based TDS checks. Sample/unverified rules are not eligible for approval or calculation.

- Missing GST, PAN, tax-rule, payment, challan, or return evidence appears as an exception. The
  application does not invent legal rates, section mappings, or supplier evidence.

- TDS deducted, deposited through a linked challan, and reported in the return are treated as
  separate amounts. A missing challan or return remains an evidence gap.

- Partial payments are evaluated cumulatively against the relevant due date; only the unpaid balance
  is at risk while an invoice remains partly unpaid.

## Executed verification

On 2026-10-23, verification was run from the repository checkout:

- `backend`: `pytest -q` — 61 passed after the final importer fix.

- `frontend`: `npm run build` — TypeScript project check and production build succeeded. Vite
  reports the existing generated JavaScript chunk is larger than 500 kB; this is a bundle-size
  warning, not a failed build.

- `backend`: `python -m compileall -q app tests`, application import (44 routes), and `alembic
upgrade head --sql` succeeded.

- Alembic `upgrade head` was applied to a clean temporary PostgreSQL 16 database; `alembic current`
  reported `91ac47bbd032 (head)`. See the README for startup commands and environment requirements.

## Task 1 payment and settlement analysis update (2026-10-24)

### Implemented calculation behavior

- Monthly dashboard rows are grouped by transaction month, gateway, payment currency, fee currency,
  and tax currency. Captured Gateway A payment rows and Gateway B charge rows are used; refund rows
  are kept out of gross payment volume and remain separately available in refund reporting.

- Fees and taxes are summed separately in their imported currencies. The combined observed-cost
  figure is present only when fee/tax currencies match and all corresponding amounts are present.
  Missing amounts are counted and are never silently treated as zero; combined cost unavailability
  distinguishes missing amounts from currency mismatch. A missing tax currency remains `UNKNOWN`
  instead of being inferred from the fee currency. Effective fee rates are omitted if the gross and
  fee currencies differ or any fee amount is missing.

- The analytics chart includes only one user-visible currency at a time and only rows whose gross
  and fee currencies match. The detailed monthly table continues to show all currency combinations
  with explicit currency labels.

- Settlement metrics are grouped by transaction month, gateway, currency, and source timing basis.
  Gateway A uses transaction-ledger `settled_at`; Gateway B separately reports balance
  `available_on` and payout-effective timestamps. Average/median elapsed hours use only valid
  nonnegative timestamp pairs. Missing completion dates, negative-duration pairs, and completion
  timestamps conflicting with an explicitly unsettled flag are counted separately. A payout-
  effective or available-on date is not independent bank receipt evidence. No settlement SLA is
  inferred from these sample records.

- Existing reconciliation compares imported ledger amounts and matching records. It does not compare
  charges with contract prices because the repo has no independently verified contract-rate
  evidence. The existing settlement delay threshold is preserved; monthly timing metrics expose
  observed duration without asserting a contractual SLA.

- Pricing scenarios require selected pricing rules that match the requested gateway and do not
  conflict with supplied currency, geography, method, or effective dates. An omitted pricing-rule
  dimension is treated as generic applicability only for the estimate and is called out as a
  limitation. Outputs explicitly say estimate-only and do not produce a reliable routing
  recommendation. The current scenario formula applies a configured fixed fee once per scenario;
  per-transaction fixed-fee units and eligible transaction counts are not modeled, so scenarios
  containing fixed fees must be treated as especially limited estimates.

- The printable executive summary now includes recent monthly volume/count and observed fees/taxes,
  settlement timings, the latest reconciliation and exception amount-at-stake by currency, and the
  latest saved scenario when one exists. Exception amount-at-stake can overlap across flags and is
  not a net loss total.

### Current verification evidence

- `backend` — `python -m pytest -q`: **62 passed**, with one pytest-asyncio deprecation warning. The
  workflow test imports all four supplied workbooks, verifies row counts/warnings/retries, monthly
  currency behavior, settlement timing coverage plus missing, negative, and status-conflicting date
  handling, reconciliation, CSV, and executive-summary content.

- `frontend` — project-local TypeScript build check (`tsc -b`) and Vite production build both
  succeeded. The output retains the existing warning about a generated JavaScript chunk exceeding
  500 kB.

- The shell `npm run build` wrapper was not usable in this environment because its configured global
  npm CLI path points to a missing `AppData\Roaming` install. The equivalent local `tsc` and `vite`
  binaries in `frontend` were run successfully.

- No schema or migration changes were needed for these additions. A fresh PostgreSQL migration was
  therefore not rerun for this task; the earlier clean-database migration evidence above remains the
  latest migration run.

### Remaining limits

- The supplied data is September 2026 synthetic/dummy data. Its observed costs and settlement
  timings are examples from those source rows, not current production performance.

- Gateway B has no separate payout-transfer/bank statement in the provided workbook. Payout totals
  and payout-effective durations remain based on that workbook alone.

- No signed/verified contract-rate dataset is present, so contractual charge comparison, confirmed
  savings, and reliable gateway routing recommendations remain unavailable.

- Fixed-fee unit semantics and a transaction count for fixed-fee scenarios are absent from the
  current pricing-rule inputs; the estimator states its once-per-scenario assumption and must not be
  used as a contract quote.

## Task 2 vendor compliance update (2026-10-24)

### Implemented and checked

- GSTR-2B matching now distinguishes a confirmed invoice mismatch from missing evidence. It labels
  an invoice `missing` only when at least one record for the same supplier GSTIN and return period
  is loaded but that invoice is not among them. If that supplier/period has no records, or the GSTIN
  is absent, the check creates `GST_GSTR2B_EVIDENCE_UNAVAILABLE`, records the missing evidence, and
  does not mark the check compliant.

- The synthetic demo includes a same-period unrelated invoice to demonstrate a confirmed GSTR-2B
  mismatch, and a matching row for the exact-45-day MSME case. Its PAN mismatch case now uses a
  valid PAN format that differs from the PAN embedded in the GSTIN. Expected outcomes in
  `synthetic_data.py` were adjusted to match actual evidence and the current risk scorecard
  behavior.

- An overall vendor scorecard cannot say `compliant` while it has any recorded exception. It is
  `needs_attention` when findings exist below the high-risk score threshold, and `high_risk` above
  that threshold.

- The exception API now returns `suggested_action`, and the Vendor Compliance page displays it with
  the description, amount at stake, currency, and any missing evidence. Scorecards and vendor master
  cleanup remain available via the existing APIs and page.

- The synthetic “short TDS” invoice is not reported as a confirmed short deduction: seeded rules
  remain unapproved samples, so the engine returns `TDS_RULE_UNVERIFIED` and requires an approved,
  effective rule. Foreign payment evidence remains explicitly unconfirmed; the workflow does not
  infer a legal threshold or documentation requirement from this demo.

- Tests cover TDS threshold boundaries and missing challan evidence, foreign vendor missing
  documents, MSME payment exactly on day 45, and a partially paid invoice whose remaining amount is
  reported as the amount at stake. They also verify all seeded vendors against `EXPECTED_OUTCOMES`
  and check scorecard, exception-report, and cleanup-list API deliverables.

### Executed verification

- `backend`: `venv\Scripts\python.exe -m pytest -q` — **70 passed**, one `pytest-asyncio`
  deprecation warning.

- `backend`: `venv\Scripts\python.exe -m pytest tests/integration/test_vendor_compliance.py -q` —
  **8 passed**, one `pytest-asyncio` deprecation warning.

- `frontend`: project-local `tsc -b` and `vite build` — both succeeded. Vite still reports the
  existing generated JavaScript chunk above 500 kB.

### Remaining limits

- Vendor, invoice, return, and challan examples are synthetic demonstration records, not provided
  sample invoice evidence or proof of real-world compliance.

- The database has no GSTR-2B upload/period manifest. Therefore an empty supplier/period is safely
  classified as evidence unavailable; completeness of a purportedly loaded period cannot be
  independently verified by this application. A confirmed mismatch is limited to the available rows
  for that supplier and period.

- No tax-team-approved rule set is supplied. Sample TDS rates are not used for deductions, and the
  demo cannot confirm statutory rate/threshold/section applicability, PAN operative status, GST
  portal status, or cross-border documentation obligations from authoritative sources. These require
  review and evidence entered in the approved environment.

- MSME elapsed-day checks use acceptance date when recorded and invoice date as the documented
  fallback. Dispute treatment and statutory interest remain subject to human/legal review; the
  application does not calculate an authoritative interest liability.

## Sample Invoice PDF ingestion (2026-10-24)

### Dataset inspection and actual import

- `data/Sample_Invoices/` contained 50 one-page PDF documents. All 50 had selectable text and were
  parsed; no OCR was needed. No OCR engine is configured, so a scanned/empty PDF is recorded as
  extraction failure and requires manual review.

- The document types extracted were 38 tax invoices, 8 generic invoices, 1 bill of supply, 1 cash
  memo, 1 debit note, and 1 proforma invoice. The currency fields were 48 INR, 1 USD, and 1 GBP. No
  amounts were converted across currencies.

- The imported PostgreSQL batch reported 50 total, 50 parsed, 0 failed, 0 duplicate, and 50 review-
  required documents. “Review required” includes successfully parsed files whose legal/compliance
  evidence is incomplete; it does not mean text extraction failed.

- Mapping results were 38 mapped tax invoices and 12 staged review records. The database has 49
  sample-dataset-linked vendor records, 38 mapped invoices, 49 generated scorecards, 291 compliance
  exceptions, and 165 open vendor-master cleanup findings. Scorecards were 40 `high_risk` and 9
  `needs_attention`; none were `compliant`. Risk scores include missing-evidence findings and do not
  establish that a vendor breached tax law.

- The scorecards did not have supportable amount-at-stake values, so those values are unavailable
  rather than shown as zero. The exception CSV contains engine findings plus document-review rows;
  one document can have several review reasons.

- PDFs are preserved by SHA-256 under the ignored runtime directory
  `backend/data/uploads/vendor_documents/`; extracted fields carry status and source evidence in
  `vendor_source_documents`. The supplied source folder `data/Sample_Invoices/` is ignored by Git.
  Re-importing the same file hash is counted as a duplicate and does not create another source
  document.

### Implemented workflow and evidence boundaries

- `POST /api/v1/vendor-compliance/documents/import` accepts multipart PDF files or ZIP files. ZIP
  members are checked for traversal and processed in memory; files are stored under hash-derived
  names. Limits are 20 MB per PDF, 100 MB per batch, and 200 PDFs. Extraction failures are isolated
  per document, and application error messages do not include invoice text.

- The sample-dataset selector filters vendors, scorecards, exceptions, checks, cleanup findings, and
  CSV exports independently from the synthetic dataset. The page shows source filenames, document
  type, extracted vendor/invoice/date/ currency/amount fields, mapping status, and review reasons.

- Only explicit, required fields from tax invoices are mapped to existing vendor/invoice models.
  Vendors are resolved by exact supplier GSTIN where present; the fallback requires exact normalized
  legal name and address. Name-only fuzzy merges are not performed. Non-tax document types and
  incomplete/non-INR invoices stay staged for review.

- The existing compliance engine generated scorecards and exceptions for the mapped invoices and
  vendor records. Missing tax components remain null; missing payment evidence does not create an
  overdue-payment conclusion. Foreign invoices remain in their stated currencies and receive tax-
  team review findings without an invented withholding rule.

- Read-only API verification returned HTTP 200 for documents (50), sample-dataset vendors (49),
  scorecards (49), exceptions (291), cleanup findings (165), and all four CSV exports. CSV line
  counts were 50 for scorecards, 361 for exceptions, 166 for cleanup, and 51 for import review (each
  includes a header).

- The API export routes are: `/api/v1/vendor-compliance/reports/scorecards.csv?source=hr`,
  `/api/v1/vendor-compliance/reports/exceptions.csv?source=hr`, `/api/v1/vendor-
compliance/reports/cleanup.csv?source=hr`, and `/api/v1/vendor-compliance/documents/export.csv`.

### Current execution evidence and limitations

- The additive PostgreSQL migration `20261024_vendor_pdf_docs` applied successfully with `alembic
upgrade head` on the configured local database. It adds source-document/import-batch tables and
  allows unknown invoice tax components to remain null. It does not rewrite existing invoice rows.

- Full backend test suite: `venv\Scripts\python.exe -m pytest -q --disable-warnings` — **74
  passed**. Focused vendor plus PDF-ingestion suite: `venv\Scripts\python.exe -m pytest
tests/integration/test_vendor_compliance.py tests/integration/test_vendor_pdf_ingestion.py -q
--disable-warnings` — **12 passed**. A `pytest-asyncio` fixture-loop deprecation warning
  appeared when warnings were enabled; `--disable-warnings` hid warning output for these two final
  result commands, not test failures.

- The backend virtual environment has `pypdf==6.10.0` installed, and the PDF tests ran directly with
  that dependency. It is also pinned in `backend/requirements.txt` for setup in another environment.

- `frontend`: `npm run build` — TypeScript (`tsc -b`) and production build succeeded. Vite emitted
  the existing warning that the generated JavaScript chunk exceeds 500 kB.

- The additive migration was applied successfully with `alembic upgrade head` to the configured
  PostgreSQL database. Read-only API checks against that database returned the imported documents,
  scorecards, exceptions, cleanup records, and CSV exports as listed above.

- `git diff --check` completed with no whitespace errors. Git printed line ending conversion
  warnings for modified files; these do not indicate diff whitespace failures.

- At the first actual import, SQLAlchemy development SQL echo printed bound structured field values
  to the terminal. `backend/app/db/session.py` now disables SQL echo, and no invoice text is sent to
  application logs. Protect any terminal captures from that initial run according to the dataset
  policy.

- The final UI/API smoke test read actual database rows and downloaded each CSV endpoint
  successfully.

### Remaining limitations

- These PDFs identify themselves as fictitious training examples. They are not the four payment-
  gateway spreadsheets and must not be represented as actual supplier compliance evidence beyond the
  fields present in each PDF.

- No GSTR-2B records, payment/bank evidence, TDS section/rate/credit timing, challans, TDS returns,
  official GST/PAN status lookup, or authoritative MSME verification accompanied the PDFs. Those
  checks remain explicit evidence gaps or manual review, not confirmed compliance.

- Tax invoice extraction uses text labels and is not a general-purpose OCR or document-understanding
  model. Ambiguous formatting, unsupported document layouts, and scanned PDFs require review. The
  mapped invoices are INR only; foreign/USD/GBP invoices are preserved as source documents and are
  not converted or pushed into INR calculations.

- Tax rates, section mappings, reverse-charge determinations, blocked-credit treatment, and legal
  conclusions still require authoritative evidence and tax-team approval. The application does not
  claim a legal compliance audit.

## Pricing & Savings feature update (2026-10-25)

- Pricing rules support create, edit, and delete. Editing can preserve omitted optional fields or
  clear fields explicitly; a rule referenced by a saved scenario cannot be deleted. Validation
  rejects invalid percentages, negative fees, malformed currency/country codes, reversed fee bounds,
  and invalid effective-date ranges.
- Scenarios require different gateways and different selected pricing rules. Rules must match the
  selected gateways and may not conflict with the scenario's currency, country, payment method, or
  effective dates. Missing percentage rates make an estimate unavailable; they are never treated as
  zero. Results are saved and can be read from scenario history.
- The current formula is percentage fee on eligible payment value, plus a configured fixed fee,
  subject to minimum/maximum fee bounds, then tax on the fee. Fixed fees are applied once per
  scenario, not per transaction; transaction count, transaction mix, and FX are not modeled.
- A focused regression test checks an illustrative INR 10,000 scenario: Gateway A at 2% + ₹5 with
  18% tax yields ₹241.90; Gateway B at 1.5% + ₹10 with 18% tax yields ₹188.80. The estimated
  difference is ₹53.10 (21.95%). These are test assumptions, not observed contract prices.
- The project-environment verification reported on 2026-10-25 includes 81 backend tests and 13
  focused workflow/pricing integration tests passing, plus a successful frontend TypeScript and Vite
  production build. See “Latest verification summary” for the audit-environment qualification.
