"""
MSME compliance checks: 45-day payment deadline (MSMED Act, 2006).

Rules applied:
- Identify vendors with MSME registration (Udyam)
- Check invoice acceptance date (or invoice date if acceptance date unavailable)
- Flag breach of 45-day payment requirement
- Account for disputed invoices (clock stops during genuine dispute)

IMPORTANT:
- MSME status must be supported by verified Udyam registration document
- Do NOT infer MSME status without explicit registration evidence
- 'Acceptance date' takes precedence over invoice date per MSMED Act, 2006, Section 2(b)
- Breach does NOT automatically invoke MSMED Act penalties without legal review
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional, Tuple, List, Dict


MSME_PAYMENT_DAYS = 45  # Maximum days allowed per MSMED Act, 2006


def check_msme_payment_deadline(
    invoice_date: date,
    acceptance_date: Optional[date],
    payment_date: Optional[date],
    is_disputed: bool = False,
    msme_type: str = "non_msme",
    udyam_number: Optional[str] = None,
    is_msme_verified: bool = False,
    paid_amount: Optional[Decimal] = None,
    invoice_amount: Optional[Decimal] = None,
    as_of_date: Optional[date] = None,
) -> Dict:
    """
    Check if payment complies with MSME 45-day rule.

    Returns a result dict with:
    - status: 'compliant'|'breach'|'pending'|'not_applicable'|'data_insufficient'
    - days_taken: int or None
    - days_remaining: int or None (if payment pending)
    - is_flagged: bool
    - explanation: str
    - missing_evidence: list of missing data items

    Note: We use acceptance_date if available; otherwise invoice_date.
    Per MSMED Act, 2006, Section 16, interest applies from day 46 at 3x bank rate.
    """
    result = {
        "status": "not_applicable",
        "days_taken": None,
        "days_remaining": None,
        "is_flagged": False,
        "explanation": "",
        "missing_evidence": [],
    }

    # Must be an MSME vendor with verified registration
    if msme_type == "non_msme":
        result["explanation"] = "Vendor is not registered as MSME — 45-day rule does not apply"
        return result

    if not is_msme_verified:
        result["status"] = "data_insufficient"
        result["is_flagged"] = True
        result["missing_evidence"].append("MSME registration not verified (Udyam certificate required)")
        result["explanation"] = "Cannot apply MSME rule: MSME registration not verified"
        return result

    if not udyam_number:
        result["status"] = "data_insufficient"
        result["is_flagged"] = True
        result["missing_evidence"].append("Udyam registration number missing")
        result["explanation"] = "Cannot apply MSME rule: Udyam number not on record"
        return result

    # Determine the effective start date
    effective_date = acceptance_date if acceptance_date else invoice_date
    if not acceptance_date:
        result["missing_evidence"].append(
            "Acceptance date not recorded — using invoice date as fallback (less accurate)"
        )

    # Disputed invoices: note limitation but do not exclude from flagging
    if is_disputed:
        result["missing_evidence"].append(
            "Invoice is marked disputed — dispute period may pause MSMED Act timeline. "
            "Legal review required."
        )

    deadline = effective_date + timedelta(days=MSME_PAYMENT_DAYS)

    if payment_date is None:
        today = as_of_date or date.today()
        days_elapsed = (today - effective_date).days
        if days_elapsed > MSME_PAYMENT_DAYS:
            result["status"] = "breach"
            result["is_flagged"] = True
            result["days_taken"] = days_elapsed
            result["explanation"] = (
                f"Payment overdue: {days_elapsed} days since invoice/acceptance date "
                f"(effective_date={effective_date}, deadline={deadline}). "
                "MSMED Act 45-day requirement breached."
            )
        else:
            result["status"] = "pending"
            result["days_remaining"] = MSME_PAYMENT_DAYS - days_elapsed
            result["explanation"] = (
                f"Payment pending: {days_elapsed} days elapsed, "
                f"deadline {deadline} ({result['days_remaining']} days remaining)."
            )
        return result

    days_taken = (payment_date - effective_date).days
    result["days_taken"] = days_taken

    if days_taken > MSME_PAYMENT_DAYS:
        result["status"] = "breach"
        result["is_flagged"] = True
        result["explanation"] = (
            f"MSME payment deadline breached: payment made {days_taken} days after "
            f"effective date (effective_date={effective_date}, payment_date={payment_date}, "
            f"limit={MSME_PAYMENT_DAYS} days). "
            "Section 16 MSMED Act: interest at 3x bank rate applies."
        )
    else:
        result["status"] = "compliant"
        result["explanation"] = (
            f"Payment made within {days_taken} days — compliant with 45-day MSME requirement."
        )

    return result


def estimate_msme_interest(
    amount: Decimal,
    breach_days: int,
    bank_rate_pct: Decimal = Decimal("6.50"),
) -> Tuple[Decimal, str]:
    """
    Estimate interest payable on delayed MSME payments.
    Per MSMED Act, 2006, Section 16: compound interest at 3x bank rate.

    bank_rate_pct: RBI bank rate — illustrative default; use current RBI published rate.
    Returns (estimated_interest, explanation_note).

    NOTE: This is an illustrative estimate only.
    Exact calculation may depend on compounding frequency and bank rate at time of breach.
    """
    if breach_days <= 0 or amount <= Decimal("0"):
        return Decimal("0"), "No breach — no interest"

    annual_rate = bank_rate_pct * Decimal("3")  # 3x bank rate
    daily_rate = annual_rate / Decimal("365") / Decimal("100")
    interest = amount * daily_rate * Decimal(str(breach_days))
    interest = interest.quantize(Decimal("0.01"))

    return interest, (
        f"Estimated interest: {interest} INR ({breach_days} days × {annual_rate}% p.a.). "
        f"Bank rate used: {bank_rate_pct}% (illustrative — verify current RBI rate). "
        "This estimate does not account for compounding."
    )


def validate_msme_udyam_format(udyam_number: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Basic format check for Udyam Registration Number.
    Format: UDYAM-XX-YY-ZZZZZZZ (where XX = state code, YY = category, ZZZZZZZ = 7 digits)
    """
    import re
    if not udyam_number:
        return False, "Udyam number is missing"
    pattern = re.compile(r"^UDYAM-[A-Z]{2}-\d{2}-\d{7}$")
    if not pattern.match(udyam_number.strip().upper()):
        return False, (
            f"'{udyam_number}' does not match Udyam format UDYAM-XX-00-0000000"
        )
    return True, None
