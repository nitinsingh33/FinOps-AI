# Accuracy and verification report

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
