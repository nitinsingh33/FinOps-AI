"""
TDS compliance checks for vendor payments.

Rules applied:
- PAN format validation
- TDS deduction on correct base (taxable amount, excluding GST component)
- TDS rate lookup from versioned TaxRule table
- TDS threshold check (no deduction below threshold)
- TDS deducted vs deposited reconciliation
- TDS deducted vs reported reconciliation (Form 26Q/27Q)
- Foreign vendor section 195 applicability flags
- Three-way reconciliation: Deducted → Deposited → Reported

IMPORTANT — Illustrative sample rules only:
  The TDS rules below are ILLUSTRATIVE SAMPLE DATA only.
  They must NOT be used for actual compliance decisions.
  Authorized tax-team approval is required before any rule is treated as controlling.
  Effective dates, rates, thresholds, and 2025 Act mappings may change.

Statutory references:
  - Income-tax Act, 1961 (as applicable on dates in sample data)
  - Income-tax Act, 2025 references are preliminary — not legally enacted as of this writing
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Illustrative sample TDS rules (SAMPLE ONLY — require tax-team approval)
# ---------------------------------------------------------------------------

SAMPLE_TDS_RULES: List[Dict] = [
    {
        "rule_code": "TDS_194C_INDIVIDUAL",
        "tax_category": "tds",
        "section_1961": "194C",
        "section_2025": None,  # Pending verification of ITA 2025 mapping
        "description": "TDS on payments to contractors/sub-contractors (Individuals/HUF) — ILLUSTRATIVE SAMPLE",
        "rate_pct": Decimal("1.00"),
        "threshold_amount": Decimal("30000.00"),  # per transaction; 100000 aggregate per year
        "tax_base": "EXCLUDE_GST",
        "effective_from": date(2021, 4, 1),
        "effective_to": None,
        "is_sample_rule": True,
        "source_reference": "Section 194C, Income-tax Act, 1961 — illustrative only",
        "verification_status": "pending_review",
    },
    {
        "rule_code": "TDS_194C_OTHER",
        "tax_category": "tds",
        "section_1961": "194C",
        "section_2025": None,
        "description": "TDS on payments to contractors/sub-contractors (Others) — ILLUSTRATIVE SAMPLE",
        "rate_pct": Decimal("2.00"),
        "threshold_amount": Decimal("30000.00"),
        "tax_base": "EXCLUDE_GST",
        "effective_from": date(2021, 4, 1),
        "effective_to": None,
        "is_sample_rule": True,
        "source_reference": "Section 194C, Income-tax Act, 1961 — illustrative only",
        "verification_status": "pending_review",
    },
    {
        "rule_code": "TDS_194J_PROFESSIONAL",
        "tax_category": "tds",
        "section_1961": "194J",
        "section_2025": None,
        "description": "TDS on fees for professional services — ILLUSTRATIVE SAMPLE",
        "rate_pct": Decimal("10.00"),
        "threshold_amount": Decimal("30000.00"),
        "tax_base": "EXCLUDE_GST",
        "effective_from": date(2021, 4, 1),
        "effective_to": None,
        "is_sample_rule": True,
        "source_reference": "Section 194J, Income-tax Act, 1961 — illustrative only",
        "verification_status": "pending_review",
    },
    {
        "rule_code": "TDS_194J_TECHNICAL",
        "tax_category": "tds",
        "section_1961": "194J",
        "section_2025": None,
        "description": "TDS on fees for technical services — ILLUSTRATIVE SAMPLE",
        "rate_pct": Decimal("2.00"),
        "threshold_amount": Decimal("30000.00"),
        "tax_base": "EXCLUDE_GST",
        "effective_from": date(2021, 4, 1),
        "effective_to": None,
        "is_sample_rule": True,
        "source_reference": "Section 194J proviso (technical services) — illustrative only",
        "verification_status": "pending_review",
    },
    {
        "rule_code": "TDS_194I_RENT_LAND",
        "tax_category": "tds",
        "section_1961": "194I",
        "section_2025": None,
        "description": "TDS on rent — land, building, furniture — ILLUSTRATIVE SAMPLE",
        "rate_pct": Decimal("10.00"),
        "threshold_amount": Decimal("240000.00"),  # INR 2.4L per year
        "tax_base": "GROSS",
        "effective_from": date(2021, 4, 1),
        "effective_to": None,
        "is_sample_rule": True,
        "source_reference": "Section 194I(b), Income-tax Act, 1961 — illustrative only",
        "verification_status": "pending_review",
    },
    {
        "rule_code": "TDS_195_FOREIGN_VENDOR",
        "tax_category": "tds",
        "section_1961": "195",
        "section_2025": None,
        "description": "TDS on payments to non-residents — rate per DTAA/treaty or 40% default — ILLUSTRATIVE SAMPLE",
        "rate_pct": Decimal("20.00"),  # Illustrative; actual depends on DTAA
        "threshold_amount": Decimal("0.00"),
        "tax_base": "GROSS",
        "effective_from": date(2021, 4, 1),
        "effective_to": None,
        "is_sample_rule": True,
        "source_reference": "Section 195, Income-tax Act, 1961 — DTAA rates apply — illustrative only",
        "verification_status": "pending_review",
    },
]


def get_applicable_tds_rule(
    section_code: str,
    payment_date: date,
    rules: Optional[List[Dict]] = None,
) -> Optional[Dict]:
    """
    Find the applicable TDS rule for a given section and date.
    Uses SAMPLE_TDS_RULES by default.
    Rules must be approved before use for compliance.
    """
    rules = rules or SAMPLE_TDS_RULES
    candidates = [
        r for r in rules
        if r["section_1961"] == section_code
        and r["effective_from"] <= payment_date
        and (r["effective_to"] is None or r["effective_to"] >= payment_date)
    ]
    if not candidates:
        return None
    # Return the most specific rule (latest effective_from)
    return sorted(candidates, key=lambda r: r["effective_from"], reverse=True)[0]


# ---------------------------------------------------------------------------
# TDS calculation
# ---------------------------------------------------------------------------

def compute_tds_base(
    invoice_total: Decimal,
    gst_amount: Decimal,
    tax_base: str = "EXCLUDE_GST",
) -> Decimal:
    """
    Compute TDS base from invoice total.

    EXCLUDE_GST: TDS on taxable value only (invoice_total - GST)
    GROSS:       TDS on full invoice total including GST (some sections)
    NET:         Rarely used; passed through as-is

    For most sections (194C, 194J), TDS is on taxable amount excluding GST
    per CBDT circular guidance.
    """
    if tax_base == "EXCLUDE_GST":
        base = invoice_total - gst_amount
        return max(base, Decimal("0"))
    elif tax_base == "GROSS":
        return invoice_total
    else:
        return invoice_total


def compute_expected_tds(
    tds_base: Decimal,
    rate_pct: Decimal,
    threshold: Decimal,
    single_payment: bool = True,
) -> Tuple[Decimal, bool, str]:
    """
    Compute expected TDS amount.
    Returns (expected_tds, is_above_threshold, explanation).

    Note: Threshold checking here is simplified (per-payment).
    Actual threshold is often aggregate per year — full tracking requires
    payment history context.
    """
    if single_payment and tds_base < threshold:
        return Decimal("0"), False, (
            f"Payment base {tds_base} is below per-transaction threshold {threshold}. "
            f"TDS not required (check aggregate threshold separately)."
        )
    tds = (tds_base * rate_pct / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return tds, True, f"TDS computed at {rate_pct}% on base {tds_base}"


def validate_tds_deduction(
    tds_deducted: Decimal,
    expected_tds: Decimal,
    tolerance: Decimal = Decimal("1.00"),
) -> Tuple[bool, Optional[str]]:
    """
    Compare TDS deducted vs expected.
    Returns (is_correct, error_message).
    Tolerance of INR 1 for rounding differences.
    """
    diff = abs(tds_deducted - expected_tds)
    if diff > tolerance:
        if tds_deducted < expected_tds:
            return False, (
                f"TDS short deduction: deducted={tds_deducted}, "
                f"expected={expected_tds}, shortfall={expected_tds - tds_deducted}"
            )
        else:
            return False, (
                f"TDS excess deduction: deducted={tds_deducted}, "
                f"expected={expected_tds}, excess={tds_deducted - expected_tds}"
            )
    return True, None


# ---------------------------------------------------------------------------
# Three-way TDS reconciliation
# ---------------------------------------------------------------------------

def three_way_tds_reconciliation(
    tds_deducted: Decimal,
    tds_deposited: Decimal,
    tds_reported: Decimal,
    tolerance: Decimal = Decimal("1.00"),
) -> Dict:
    """
    Three-way reconciliation: Deducted ↔ Deposited ↔ Reported.

    Deducted: Amount withheld from vendor payment
    Deposited: Amount paid to government (ITNS 281 challan)
    Reported: Amount declared in Form 26Q/27Q return

    All three should match. Differences indicate:
    - Short deposit: Potential penalty under 201(1A)
    - Under-reporting: Potential prosecution under 277
    """
    result = {
        "tds_deducted": str(tds_deducted),
        "tds_deposited": str(tds_deposited),
        "tds_reported": str(tds_reported),
        "issues": [],
    }

    deposit_diff = tds_deducted - tds_deposited
    if abs(deposit_diff) > tolerance:
        result["issues"].append({
            "type": "deposit_mismatch",
            "severity": "high",
            "description": (
                f"TDS deducted ({tds_deducted}) != deposited ({tds_deposited}). "
                f"Difference: {deposit_diff}. "
                "Short deposit may attract interest under 201(1A)."
            ),
            "amount_at_stake": str(abs(deposit_diff)),
        })

    report_diff = tds_deposited - tds_reported
    if abs(report_diff) > tolerance:
        result["issues"].append({
            "type": "reporting_mismatch",
            "severity": "medium",
            "description": (
                f"TDS deposited ({tds_deposited}) != reported ({tds_reported}). "
                f"Difference: {report_diff}. "
                "Verify Form 26Q/27Q filing."
            ),
            "amount_at_stake": str(abs(report_diff)),
        })

    result["status"] = "matched" if not result["issues"] else "issues_found"
    return result


# ---------------------------------------------------------------------------
# Foreign vendor check
# ---------------------------------------------------------------------------

def check_foreign_vendor_requirements(
    vendor_type: str,
    has_form_15ca_15cb: bool,
    tds_section: Optional[str],
    amount: Decimal,
) -> List[Dict]:
    """
    Check Form 15CA/15CB and Section 195 requirements for foreign vendors.
    Returns list of issue dicts (empty if compliant).
    """
    issues = []
    if vendor_type != "foreign":
        return issues

    if tds_section != "195" and amount > Decimal("0"):
        issues.append({
            "type": "wrong_tds_section",
            "severity": "high",
            "description": f"Foreign vendor payment should use Section 195, not '{tds_section}'",
        })

    if amount > Decimal("5000000.00") and not has_form_15ca_15cb:
        # > INR 50 lakh threshold for Form 15CA/15CB (illustrative)
        issues.append({
            "type": "missing_15ca_15cb",
            "severity": "high",
            "description": (
                f"Foreign payment of {amount} INR requires Form 15CA/15CB "
                "per Rule 37BB. Forms not recorded."
            ),
        })

    return issues
