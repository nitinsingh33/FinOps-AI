"""
GST compliance checks for vendor records.

Rules applied:
- GSTIN format validation (15-char alphanumeric, statecode-PAN-entity-check)
- PAN format validation (10-char: AAAAA9999A pattern)
- PAN-GSTIN consistency check
- Supply type routing: intra-state → CGST+SGST, inter-state → IGST
- GSTR-2B matching check
- ITC 180-day payment rule
- Blocked ITC categories (Section 17(5) CGST Act)
- Reverse charge applicability flag

Note on regulatory references:
  All rule references (CGST Act, IGST Act, Income-tax Act, 1961) are informational.
  Tax-team approval is required before treating any rule as controlling law.

GSTIN structure: SS PPPPPPPPP E Z C
  SS    = 2-digit state code
  PPPPP = PAN (10 chars)
  E     = entity number (1-9, A-Z)
  Z     = always 'Z' in current format
  C     = checksum character
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# GSTIN validation
# ---------------------------------------------------------------------------

# Standard GSTIN regex: 2-digit state + 10-char PAN + 1 entity + Z + checksum
GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")

# PAN format: AAAAA9999A  (5 uppercase alpha + 4 digits + 1 uppercase alpha)
PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")


def validate_gstin_format(gstin: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate GSTIN format only — not active status.
    Returns (is_valid, error_message).
    Format validation is NOT a substitute for GST portal status verification.
    """
    if not gstin:
        return False, "GSTIN is missing or empty"
    gstin = str(gstin).strip().upper()
    if len(gstin) != 15:
        return False, f"GSTIN must be 15 characters; got {len(gstin)}"
    if not GSTIN_REGEX.match(gstin):
        return False, f"GSTIN '{gstin}' does not match expected pattern (SSXXXXXDDDDXZZC)"
    return True, None


def validate_pan_format(pan: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Validate PAN format — not operative status.
    Returns (is_valid, error_message).
    """
    if not pan:
        return False, "PAN is missing or empty"
    pan = str(pan).strip().upper()
    if len(pan) != 10:
        return False, f"PAN must be 10 characters; got {len(pan)}"
    if not PAN_REGEX.match(pan):
        return False, f"PAN '{pan}' does not match pattern AAAAA9999A"
    return True, None


def extract_pan_from_gstin(gstin: str) -> Optional[str]:
    """
    Extract embedded PAN from a GSTIN (characters 3-12, 0-indexed 2:12).
    Returns None if GSTIN format is invalid.
    """
    if not gstin or len(gstin) != 15:
        return None
    return gstin[2:12].upper()


def check_pan_gstin_consistency(pan: Optional[str], gstin: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Verify that the PAN embedded in GSTIN matches the vendor's declared PAN.
    Returns (is_consistent, error_message).
    """
    if not pan or not gstin:
        return False, "Cannot check consistency: PAN or GSTIN is missing"
    pan = pan.strip().upper()
    embedded_pan = extract_pan_from_gstin(gstin.strip().upper())
    if embedded_pan is None:
        return False, "Cannot extract PAN from GSTIN — invalid GSTIN format"
    if pan != embedded_pan:
        return False, f"PAN mismatch: vendor PAN={pan}, GSTIN embeds PAN={embedded_pan}"
    return True, None


# ---------------------------------------------------------------------------
# GST supply type check
# ---------------------------------------------------------------------------

def determine_gst_type(pos_state_code: str, recipient_state_code: str,
                        is_rcm: bool = False) -> str:
    """
    Determine whether IGST or CGST+SGST applies.

    Rule (Section 8/9/10 CGST Act):
    - If POS == recipient state → intra-state → CGST + SGST
    - If POS != recipient state → inter-state → IGST
    - RCM does not change this routing rule

    Returns 'IGST' or 'CGST_SGST'.
    """
    if pos_state_code == recipient_state_code:
        return "CGST_SGST"
    return "IGST"


def validate_invoice_gst_treatment(
    supply_type: str,  # "intra_state" or "inter_state"
    cgst: Decimal,
    sgst: Decimal,
    igst: Decimal,
    is_rcm: bool = False,
) -> Tuple[bool, Optional[str]]:
    """
    Verify that the correct GST component is used based on declared supply type.
    Returns (is_correct, error_message).
    """
    # In a reverse-charge transaction the recipient accounts for GST. GST
    # charged by the supplier is therefore a document exception; routing is
    # still determined by place of supply when recipient-side tax is assessed.
    if is_rcm and any(value > Decimal("0") for value in (cgst, sgst, igst)):
        return False, "Reverse-charge invoice records supplier-charged GST; verify the invoice and recipient-side tax evidence."
    if supply_type == "intra_state":
        if igst > Decimal("0"):
            return False, (
                f"Intra-state supply should use CGST+SGST, not IGST. "
                f"IGST={igst} but supply_type=intra_state."
            )
        return True, None
    elif supply_type == "inter_state":
        if cgst > Decimal("0") or sgst > Decimal("0"):
            return False, (
                f"Inter-state supply should use IGST, not CGST+SGST. "
                f"CGST={cgst}, SGST={sgst} but supply_type=inter_state."
            )
        return True, None
    else:
        return False, f"Unknown supply_type: {supply_type}"


# ---------------------------------------------------------------------------
# ITC 180-day payment rule (Section 16(2)(b) CGST Act)
# ---------------------------------------------------------------------------

ITC_PAYMENT_DAYS = 180  # days from invoice date to pay supplier


def check_itc_180_day_rule(
    invoice_date: date,
    payment_date: Optional[date],
    paid_amount: Optional[Decimal] = None,
    invoice_amount: Optional[Decimal] = None,
    as_of_date: Optional[date] = None,
) -> Tuple[str, Optional[str]]:
    """
    Check ITC eligibility based on 180-day payment rule.
    Returns ('eligible'|'reversal_required'|'pending', explanation).

    - If payment_date is None: ITC is at risk (not yet paid)
    - If paid within 180 days: ITC is retained
    - If not paid within 180 days: ITC must be reversed (with interest)
    """
    fully_paid = (paid_amount is None or invoice_amount is None or paid_amount >= invoice_amount)
    check_date = payment_date if fully_paid else (as_of_date or date.today())
    if check_date is None:
        return "pending", "Payment date unknown — ITC eligibility cannot be confirmed"

    days = (check_date - invoice_date).days
    if days <= ITC_PAYMENT_DAYS:
        if not fully_paid and days >= 0:
            return "pending", f"Invoice is only partially paid ({paid_amount} of {invoice_amount}); unpaid balance remains within the 180-day period."
        return "eligible", None
    return "reversal_required", (
        f"Unpaid consideration remained {days} days after invoice date (limit: {ITC_PAYMENT_DAYS} days). "
        f"ITC of INR {{}} must be reversed with applicable interest."
    )


# ---------------------------------------------------------------------------
# Blocked ITC categories (Section 17(5) CGST Act)
# ---------------------------------------------------------------------------

BLOCKED_ITC_CATEGORIES = {
    "motor_vehicle": "Motor vehicles for <13-person transport — ITC blocked per 17(5)(a)",
    "food_beverage": "Food and beverages — ITC blocked per 17(5)(b)",
    "beauty_health": "Beauty treatment, health services — ITC blocked per 17(5)(b)",
    "personal_consumption": "Goods/services for personal consumption — ITC blocked per 17(5)(l)",
    "club_membership": "Membership of club, health, fitness — ITC blocked per 17(5)(b)",
    "works_contract": "Works contract services for immovable property — ITC blocked per 17(5)(c)",
    "construction": "Goods/services for construction of immovable property — ITC blocked per 17(5)(d)",
}


def check_blocked_itc(blocked_itc_category: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Returns (is_blocked, reason_message).
    Only checks known blocked categories — is not a complete legal analysis.
    """
    if not blocked_itc_category:
        return False, None
    reason = BLOCKED_ITC_CATEGORIES.get(blocked_itc_category.lower())
    if reason:
        return True, reason
    return False, None


# ---------------------------------------------------------------------------
# GSTR-2B matching check
# ---------------------------------------------------------------------------

def check_gstr2b_match(
    invoice_number: str,
    gstin_supplier: str,
    return_period: str,
    gstr2b_invoices: list,  # list of dicts with invoice_number, gstin_supplier, return_period
) -> Tuple[str, Optional[str]]:
    """
    Check if invoice appears in GSTR-2B.
    Returns ('matched'|'missing'|'data_unavailable', explanation).

    IMPORTANT: This performs exact-match on invoice_number + gstin_supplier + return_period.
    Format differences (casing, spacing) may cause false mismatches.
    """
    inv_norm = invoice_number.strip().upper() if invoice_number else ""
    gstin_norm = gstin_supplier.strip().upper() if gstin_supplier else ""
    if not inv_norm or not gstin_norm or not return_period:
        return "data_unavailable", "Invoice, supplier GSTIN, or return period is missing"

    period_records = [
        rec for rec in gstr2b_invoices
        if rec.get("gstin_supplier", "").strip().upper() == gstin_norm
        and rec.get("return_period", "") == return_period
    ]
    if not period_records:
        return "data_unavailable", (
            f"No GSTR-2B evidence is available for supplier {gstin_supplier} "
            f"in period {return_period}; absence cannot be confirmed."
        )

    for rec in period_records:
        if rec.get("invoice_number", "").strip().upper() == inv_norm:
            return "matched", None

    return "missing", (
        f"Invoice {invoice_number} from supplier {gstin_supplier} "
        f"not found in GSTR-2B for period {return_period}. "
        "Verify with supplier that GSTR-1 was filed correctly."
    )
