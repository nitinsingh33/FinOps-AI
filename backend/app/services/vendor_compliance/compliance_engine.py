"""
Vendor Compliance Engine — orchestrates GST, TDS, MSME, and master data checks.

Produces:
- VendorComplianceException records for each detected issue
- VendorScorecard per vendor (Compliant / Needs Attention / High Risk)
- VendorMasterCleanupItem for data quality issues

Risk scoring:
- HIGH severity exception:     +30 points
- MEDIUM severity exception:   +15 points
- LOW severity exception:       +5 points
- Unverified GSTIN/PAN:        +10 points each
- Unverified MSME:             +5 points

Score 0-25 with no exceptions: Compliant
Any recorded finding below 61: Needs Attention
Score 61+: High Risk

Prevent double-counting:
- Per-invoice exceptions reference specific invoice evidence
- Vendor scorecard totals amount_at_stake at vendor level, not exception level
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.vendor_compliance import (
    ComplianceStatus, SeverityLevel,
    VendorComplianceException, VendorMaster, VendorInvoice,
    VendorPayment, GSTR2BRecord, TDSChallan, TDSReturnRecord,
    VendorScorecard, VendorMasterCleanupItem, VendorSourceDocument, TaxRule, TDSChallan,
)
from app.services.vendor_compliance.gst_checks import (
    validate_gstin_format, validate_pan_format, check_pan_gstin_consistency,
    validate_invoice_gst_treatment, check_itc_180_day_rule, check_blocked_itc,
    check_gstr2b_match,
)
from app.services.vendor_compliance.tds_checks import (
    compute_tds_base, compute_expected_tds, validate_tds_deduction,
    three_way_tds_reconciliation,
)
from app.services.vendor_compliance.msme_checks import (
    check_msme_payment_deadline, validate_msme_udyam_format,
)


SCORE_WEIGHTS = {
    "high": 30,
    "medium": 15,
    "low": 5,
}

SCORE_THRESHOLDS = {
    "compliant": 25,
    "needs_attention": 60,
}


def _gen_id() -> str:
    return str(uuid.uuid4())


def _add_exception(
    db: Session,
    vendor_id: str,
    check_code: str,
    category: str,
    severity: str,
    title: str,
    description: str,
    suggested_action: str,
    invoice_id: Optional[str] = None,
    rule_code: Optional[str] = None,
    rule_version: str = "1.0",
    amount_at_stake: Optional[Decimal] = None,
    currency: str = "INR",
    calculation_breakdown: Optional[Dict] = None,
    evidence: Optional[Dict] = None,
    missing_information: Optional[List[str]] = None,
    is_synthetic_warning: Optional[bool] = None,
) -> VendorComplianceException:
    if is_synthetic_warning is None:
        source_vendor = db.query(VendorMaster.is_synthetic).filter_by(id=vendor_id).scalar()
        is_synthetic_warning = bool(source_vendor)
    exc = VendorComplianceException(
        id=_gen_id(),
        check_code=check_code,
        category=category,
        severity=severity,
        vendor_id=vendor_id,
        invoice_id=invoice_id,
        rule_code=rule_code,
        rule_version=rule_version,
        title=title,
        description=description,
        amount_at_stake=amount_at_stake,
        currency=currency,
        calculation_breakdown=calculation_breakdown,
        evidence=evidence or {},
        missing_information=missing_information or [],
        suggested_action=suggested_action,
        review_status="open",
        is_synthetic_warning=is_synthetic_warning,
    )
    db.add(exc)
    return exc


def run_vendor_compliance_checks(db: Session, vendor_id: str) -> VendorScorecard:
    """
    Run all compliance checks for a single vendor and persist results.
    Idempotent: clears and recreates exceptions + scorecard each run.
    """
    vendor = db.query(VendorMaster).filter_by(id=vendor_id).first()
    if not vendor:
        raise ValueError(f"Vendor {vendor_id} not found")

    # Clear existing exceptions for this vendor (re-runnable)
    db.query(VendorComplianceException).filter_by(vendor_id=vendor_id).delete()
    db.query(VendorScorecard).filter_by(vendor_id=vendor_id).delete()
    db.flush()

    exceptions: List[VendorComplianceException] = []
    risk_score = 0

    # -----------------------------------------------------------------------
    # 1. Master data / GSTIN-PAN checks
    # -----------------------------------------------------------------------
    hr_foreign = vendor.vendor_type == "foreign" and not vendor.is_synthetic
    gstin_valid, gstin_err = ((True, None) if hr_foreign else validate_gstin_format(vendor.gstin))
    if not gstin_valid:
        exc = _add_exception(
            db, vendor_id,
            check_code="MASTER_GSTIN_FORMAT",
            category="master_data",
            severity="high",
            title="Invalid GSTIN format",
            description=f"Vendor GSTIN '{vendor.gstin}' failed format check: {gstin_err}",
            suggested_action="Obtain correct GSTIN from vendor and update master record. "
                             "Verify on GST portal.",
            evidence={"gstin": vendor.gstin, "format_error": gstin_err},
        )
        exceptions.append(exc)
        risk_score += SCORE_WEIGHTS["high"]

    pan_valid, pan_err = ((True, None) if hr_foreign and not vendor.pan else validate_pan_format(vendor.pan))
    if not pan_valid:
        exc = _add_exception(
            db, vendor_id,
            check_code="MASTER_PAN_FORMAT",
            category="master_data",
            severity="high",
            title="Invalid PAN format",
            description=f"Vendor PAN '{vendor.pan}' failed format check: {pan_err}",
            suggested_action="Collect PAN card copy from vendor and verify.",
            evidence={"pan": vendor.pan, "format_error": pan_err},
        )
        exceptions.append(exc)
        risk_score += SCORE_WEIGHTS["high"]

    if not hr_foreign and gstin_valid and pan_valid:
        consistent, consistency_err = check_pan_gstin_consistency(vendor.pan, vendor.gstin)
        if not consistent:
            exc = _add_exception(
                db, vendor_id,
                check_code="MASTER_PAN_GSTIN_MISMATCH",
                category="master_data",
                severity="high",
                title="PAN and GSTIN do not match",
                description=consistency_err,
                suggested_action="Contact vendor to clarify — possible fraudulent or outdated GSTIN.",
                evidence={"pan": vendor.pan, "gstin": vendor.gstin},
            )
            exceptions.append(exc)
            risk_score += SCORE_WEIGHTS["high"]

    if not vendor.is_gstin_verified and not hr_foreign:
        exc = _add_exception(db, vendor_id, "MASTER_GSTIN_EVIDENCE_MISSING", "master_data", "medium",
            "GSTIN evidence not verified", "The GSTIN format is not proof of active registration.",
            "Verify registration status using an authoritative GST source.",
            missing_information=["GST portal verification evidence"], evidence={"gstin": vendor.gstin})
        exceptions.append(exc)
        risk_score += 10

    if not vendor.is_pan_verified and (not hr_foreign or vendor.pan):
        exc = _add_exception(db, vendor_id, "MASTER_PAN_EVIDENCE_MISSING", "master_data", "medium",
            "PAN evidence not verified", "PAN format is not proof of operative status or ownership.",
            "Verify PAN and operative status against authoritative evidence.",
            missing_information=["PAN verification evidence"], evidence={"pan": vendor.pan})
        exceptions.append(exc)
        risk_score += 10

    # MSME format check
    if vendor.msme_type != "non_msme" and vendor.udyam_number:
        udyam_valid, udyam_err = validate_msme_udyam_format(vendor.udyam_number)
        if not udyam_valid:
            exc = _add_exception(
                db, vendor_id,
                check_code="MASTER_UDYAM_FORMAT",
                category="master_data",
                severity="medium",
                title="Invalid Udyam registration number format",
                description=f"Udyam number '{vendor.udyam_number}' is malformed: {udyam_err}",
                suggested_action="Obtain Udyam certificate from vendor and verify on Udyam portal.",
                evidence={"udyam_number": vendor.udyam_number},
            )
            exceptions.append(exc)
            risk_score += SCORE_WEIGHTS["medium"]

    # -----------------------------------------------------------------------
    # 2. Invoice-level GST and TDS checks
    # -----------------------------------------------------------------------
    invoices = db.query(VendorInvoice).filter_by(vendor_id=vendor_id).all()
    payments_by_invoice: Dict[str, List[VendorPayment]] = {}
    all_payments = db.query(VendorPayment).filter_by(vendor_id=vendor_id).all()
    for pmt in all_payments:
        if pmt.invoice_id:
            payments_by_invoice.setdefault(pmt.invoice_id, []).append(pmt)

    # Load GSTR-2B records for matching
    gstr2b_records = []
    if vendor.gstin:
        gstr2b_rows = db.query(GSTR2BRecord).filter_by(gstin_supplier=vendor.gstin).all()
        gstr2b_records = [
            {
                "invoice_number": r.invoice_number,
                "gstin_supplier": r.gstin_supplier,
                "return_period": r.return_period,
            }
            for r in gstr2b_rows
        ]

    for inv in invoices:
        # GST treatment check
        components = (inv.cgst_amount, inv.sgst_amount, inv.igst_amount)
        components_known = all(value is not None for value in components)
        if components_known:
            gst_ok, gst_err = validate_invoice_gst_treatment(
                inv.supply_type, *components, inv.is_rcm
            )
            gst_check_code = "GST_WRONG_TAX_TYPE"
        else:
            gst_ok, gst_err = False, "Tax component amounts are missing from the source invoice; tax treatment cannot be confirmed."
            gst_check_code = "GST_TAX_BREAKUP_EVIDENCE_MISSING"
        if not gst_ok:
            exc = _add_exception(
                db, vendor_id,
                check_code=gst_check_code,
                category="gst",
                severity="high" if components_known else "medium",
                title=(f"Incorrect GST type on invoice {inv.invoice_number}" if components_known else f"Tax breakup evidence missing for invoice {inv.invoice_number}"),
                description=gst_err,
                suggested_action=("Request corrected invoice from vendor with correct CGST/SGST or IGST." if components_known else "Obtain a complete tax breakup before assessing invoice tax treatment."),
                invoice_id=inv.id,
                evidence={
                    "invoice_number": inv.invoice_number,
                    "supply_type": inv.supply_type,
                    "cgst": str(inv.cgst_amount) if inv.cgst_amount is not None else None,
                    "sgst": str(inv.sgst_amount) if inv.sgst_amount is not None else None,
                    "igst": str(inv.igst_amount) if inv.igst_amount is not None else None,
                },
                amount_at_stake=inv.total_tax_amount if components_known else None,
                missing_information=["CGST, SGST/UTGST and IGST amounts"] if not components_known else None,
            )
            exceptions.append(exc)
            risk_score += SCORE_WEIGHTS["high"]

        # A missing GSTR-2B record is only a confirmed mismatch when source
        # evidence for the same supplier and period exists. Otherwise record
        # an evidence gap; never infer a match from an empty/unloaded period.
        inv_date = inv.invoice_date
        return_period = f"{inv_date.month:02d}{inv_date.year}"
        status, gstr2b_msg = check_gstr2b_match(
            inv.invoice_number, vendor.gstin or "", return_period, gstr2b_records
        )
        if status in ("missing", "data_unavailable"):
            confirmed_mismatch = status == "missing"
            exc = _add_exception(
                db, vendor_id,
                check_code=("GST_GSTR2B_MISSING" if confirmed_mismatch
                            else "GST_GSTR2B_EVIDENCE_UNAVAILABLE"),
                category="gst",
                severity="medium",
                title=(f"Invoice {inv.invoice_number} not found in GSTR-2B"
                       if confirmed_mismatch else
                       f"GSTR-2B evidence unavailable for invoice {inv.invoice_number}"),
                description=gstr2b_msg,
                suggested_action=("Follow up with vendor to file GSTR-1. Do not claim ITC until invoice appears in GSTR-2B."
                                  if confirmed_mismatch else
                                  "Load the supplier's GSTR-2B records for this return period and verify the invoice before claiming ITC."),
                invoice_id=inv.id,
                evidence={
                    "invoice_number": inv.invoice_number,
                    "return_period": return_period,
                    "gstin_supplier": vendor.gstin,
                    "match_status": status,
                },
                missing_information=(None if confirmed_mismatch else [
                    "Supplier GSTIN evidence" if not vendor.gstin else
                    f"GSTR-2B source evidence for return period {return_period}"
                ]),
                amount_at_stake=inv.total_tax_amount,
            )
            exceptions.append(exc)
            risk_score += SCORE_WEIGHTS["medium"]

        # Blocked ITC check
        itc_blocked, itc_reason = check_blocked_itc(inv.blocked_itc_category)
        if itc_blocked or inv.is_blocked_itc_17_5:
            exc = _add_exception(
                db, vendor_id,
                check_code="GST_BLOCKED_ITC",
                category="gst",
                severity="high",
                title=f"Blocked ITC on invoice {inv.invoice_number}",
                description=itc_reason or "ITC blocked per Section 17(5) CGST Act",
                suggested_action="Reverse ITC claim if already taken. Do not claim in future returns.",
                invoice_id=inv.id,
                evidence={"invoice_number": inv.invoice_number, "category": inv.blocked_itc_category},
                amount_at_stake=inv.total_tax_amount,
            )
            exceptions.append(exc)
            risk_score += SCORE_WEIGHTS["high"]

        # ITC 180-day rule
        inv_payments = payments_by_invoice.get(inv.id, [])
        paid_total = sum((p.gross_amount_paid for p in inv_payments), Decimal("0"))
        cumulative = Decimal("0")
        full_payment_date = None
        for pmt in sorted(inv_payments, key=lambda p: p.payment_date):
            cumulative += pmt.gross_amount_paid
            if cumulative >= inv.total_amount:
                full_payment_date = pmt.payment_date
                break
        if not vendor.is_synthetic and not inv_payments:
            itc_status, itc_msg = "evidence_missing", None
            exc = _add_exception(db, vendor_id, "GST_ITC_PAYMENT_EVIDENCE_MISSING", "gst", "medium",
                f"Payment evidence unavailable for invoice {inv.invoice_number}",
                "Invoice evidence does not establish whether or when payment occurred; no overdue conclusion was inferred.",
                "Provide invoice-linked payment records before assessing the 180-day condition.",
                invoice_id=inv.id, missing_information=["Invoice-linked payment dates and amounts"],
                evidence={"invoice_number": inv.invoice_number, "invoice_date": str(inv.invoice_date)})
            exceptions.append(exc)
            risk_score += SCORE_WEIGHTS["medium"]
        else:
            itc_status, itc_msg = check_itc_180_day_rule(
                inv.invoice_date, full_payment_date, paid_total, inv.total_amount
            )
        if itc_status == "reversal_required":
            exc = _add_exception(
                db, vendor_id,
                check_code="GST_ITC_180_DAY",
                category="gst",
                severity="high",
                title=f"ITC reversal required — 180-day rule breached (Invoice {inv.invoice_number})",
                description=itc_msg.format(str(inv.total_tax_amount)),
                suggested_action="Reverse ITC in current period GSTR-3B and pay interest.",
                invoice_id=inv.id,
                evidence={
                    "invoice_number": inv.invoice_number,
                    "invoice_date": str(inv.invoice_date),
                    "payment_date": str(full_payment_date) if full_payment_date else "partial or unpaid",
                    "paid_amount": str(paid_total),
                    "invoice_amount": str(inv.total_amount),
                },
                amount_at_stake=(inv.total_tax_amount if full_payment_date else
                    inv.total_tax_amount * max(inv.total_amount - paid_total, Decimal("0")) / inv.total_amount
                    if inv.total_amount else inv.total_tax_amount),
            )
            exceptions.append(exc)
            risk_score += SCORE_WEIGHTS["high"]

        # TDS checks
        if inv.tds_section:
            active_rules = db.query(TaxRule).filter(
                TaxRule.tax_category == "tds",
                TaxRule.section_1961 == inv.tds_section,
                TaxRule.verification_status == "approved",
                TaxRule.is_sample_rule.is_(False),
                TaxRule.effective_from <= inv.invoice_date,
            ).all()
            active_rules = [r for r in active_rules if r.effective_to is None or r.effective_to >= inv.invoice_date]
            rule_obj = max(active_rules, key=lambda r: r.effective_from) if active_rules else None
            rule = ({"rule_code": rule_obj.rule_code, "rate_pct": rule_obj.rate_pct,
                     "threshold_amount": rule_obj.threshold_amount, "tax_base": rule_obj.tax_base,
                     "is_sample_rule": rule_obj.is_sample_rule, "version": rule_obj.version}
                    if rule_obj else None)
            if rule:
                if any(value is None for value in (inv.cgst_amount, inv.sgst_amount, inv.igst_amount)):
                    gst_total = None
                else:
                    gst_total = inv.cgst_amount + inv.sgst_amount + inv.igst_amount
                if gst_total is None:
                    exc = _add_exception(db, vendor_id, "TDS_GST_BASE_EVIDENCE_MISSING", "tds", "medium",
                        f"TDS base cannot be determined for invoice {inv.invoice_number}",
                        "The configured tax base depends on a complete invoice tax breakup.",
                        "Obtain a complete invoice tax breakup before calculating the TDS base.",
                        invoice_id=inv.id, missing_information=["Complete invoice tax breakup"],
                        evidence={"invoice_number": inv.invoice_number})
                    exceptions.append(exc)
                    risk_score += SCORE_WEIGHTS["medium"]
                    continue
                tds_base = compute_tds_base(inv.total_amount, gst_total, rule["tax_base"])
                expected_tds, above_threshold, _ = compute_expected_tds(
                    tds_base, rule["rate_pct"], rule["threshold_amount"]
                )
                if above_threshold:
                    tds_ok, tds_err = validate_tds_deduction(
                        inv.tds_deducted_amount, expected_tds
                    )
                    if not tds_ok:
                        exc = _add_exception(
                            db, vendor_id,
                            check_code="TDS_DEDUCTION_MISMATCH",
                            category="tds",
                            severity="high",
                            title=f"TDS deduction error on invoice {inv.invoice_number}",
                            description=tds_err,
                            suggested_action="Verify applicable TDS section and rate with tax team. "
                                             "Correct deduction in next payment.",
                            invoice_id=inv.id,
                            rule_code=rule["rule_code"],
                            evidence={
                                "section": inv.tds_section,
                                "tds_base": str(tds_base),
                                "expected_tds": str(expected_tds),
                                "deducted": str(inv.tds_deducted_amount),
                                "rule_is_sample": rule["is_sample_rule"],
                            },
                            amount_at_stake=abs(expected_tds - inv.tds_deducted_amount),
                            calculation_breakdown={
                                "invoice_total": str(inv.total_amount),
                                "gst_excluded": str(gst_total),
                                "tds_base": str(tds_base),
                                "rate_pct": str(rule["rate_pct"]),
                                "expected_tds": str(expected_tds),
                            },
                            missing_information=[
                                "Sample rule used — requires tax-team approved rate card"
                            ] if rule["is_sample_rule"] else None,
                        )
                        exceptions.append(exc)
                        risk_score += SCORE_WEIGHTS["high"]
            else:
                exc = _add_exception(db, vendor_id, "TDS_RULE_UNVERIFIED", "tds", "medium",
                    f"TDS rule not verified for invoice {inv.invoice_number}",
                    f"No approved, effective tax rule is configured for section {inv.tds_section}; no rate was assumed.",
                    "Have the tax team configure and approve a dated rule before assessing deduction.",
                    invoice_id=inv.id, missing_information=["Approved rule, source and effective date"],
                    evidence={"section": inv.tds_section, "invoice_date": str(inv.invoice_date)})
                exceptions.append(exc)
                risk_score += SCORE_WEIGHTS["medium"]
        elif not vendor.is_synthetic:
            exc = _add_exception(db, vendor_id, "TDS_ASSESSMENT_EVIDENCE_MISSING", "tds", "medium",
                f"TDS assessment evidence unavailable for invoice {inv.invoice_number}",
                "The invoice does not establish the applicable withholding section, timing, deduction, deposit or reporting.",
                "Have the tax team determine the applicable approved rule and provide credit/payment, deduction, challan and return evidence.",
                invoice_id=inv.id, missing_information=["Applicable approved TDS rule", "Credit/payment timing", "Deduction, challan and return evidence"],
                evidence={"invoice_number": inv.invoice_number})
            exceptions.append(exc)
            risk_score += SCORE_WEIGHTS["medium"]

        if vendor.vendor_type == "foreign" and not inv.has_form_15ca_15cb:
            exc = _add_exception(db, vendor_id, "TDS_FOREIGN_DOCUMENTATION_UNCONFIRMED", "tds", "medium",
                f"Cross-border payment documentation is not recorded for invoice {inv.invoice_number}",
                "Required documents and tax treatment depend on the facts and applicable rules; no threshold or section mapping was assumed.",
                "Have the tax team determine applicable documentation and record evidence.",
                invoice_id=inv.id,
                missing_information=["Tax-team determination and supporting cross-border payment documents"],
                evidence={"invoice_number": inv.invoice_number, "payment_amount": str(inv.total_amount)})
            exceptions.append(exc)
            risk_score += SCORE_WEIGHTS["medium"]

        # MSME check per invoice
        if (vendor.is_synthetic and vendor.msme_type != "non_msme") or (not vendor.is_synthetic and vendor.msme_type in ("micro", "small", "unknown")):
            inv_payments_for_msme = payments_by_invoice.get(inv.id, [])
            if not vendor.is_synthetic and vendor.msme_type == "unknown":
                exc = _add_exception(db, vendor_id, "MSME_CLASSIFICATION_EVIDENCE_MISSING", "msme", "medium",
                    f"MSME classification evidence unavailable for invoice {inv.invoice_number}",
                    "The invoice does not establish whether the supplier is micro, small or medium; no 45-day deadline conclusion was applied.",
                    "Verify current enterprise classification and Udyam evidence before applying a payment deadline.",
                    invoice_id=inv.id, missing_information=["Verified micro/small/medium classification"],
                    evidence={"invoice_number": inv.invoice_number, "udyam_number": vendor.udyam_number})
                exceptions.append(exc)
                risk_score += SCORE_WEIGHTS["medium"]
                continue
            if not vendor.is_synthetic and not inv_payments_for_msme:
                exc = _add_exception(db, vendor_id, "MSME_PAYMENT_EVIDENCE_MISSING", "msme", "medium",
                    f"MSME payment evidence unavailable for invoice {inv.invoice_number}",
                    "Invoice evidence alone does not show MSME acceptance date or payment timing; no deadline conclusion was inferred.",
                    "Verify MSME status, acceptance date and invoice-linked payment evidence before assessing the deadline.",
                    invoice_id=inv.id, missing_information=["Verified MSME status", "Acceptance date", "Invoice-linked payments"],
                    evidence={"invoice_number": inv.invoice_number, "invoice_date": str(inv.invoice_date)})
                exceptions.append(exc)
                risk_score += SCORE_WEIGHTS["medium"]
                continue
            paid_msme = sum((p.gross_amount_paid for p in inv_payments_for_msme), Decimal("0"))
            cumulative_msme = Decimal("0")
            full_payment_date_msme = None
            for pmt in sorted(inv_payments_for_msme, key=lambda p: p.payment_date):
                cumulative_msme += pmt.gross_amount_paid
                if cumulative_msme >= inv.total_amount:
                    full_payment_date_msme = pmt.payment_date
                    break
            msme_result = check_msme_payment_deadline(
                invoice_date=inv.invoice_date,
                acceptance_date=inv.acceptance_date,
                payment_date=full_payment_date_msme,
                is_disputed=inv.is_disputed,
                msme_type=vendor.msme_type,
                udyam_number=vendor.udyam_number,
                is_msme_verified=vendor.is_msme_verified,
                paid_amount=paid_msme,
                invoice_amount=inv.total_amount,
            )
            if msme_result["is_flagged"]:
                exc = _add_exception(
                    db, vendor_id,
                    check_code="MSME_45_DAY_BREACH",
                    category="msme",
                    severity="high",
                    title=f"MSME 45-day deadline issue on invoice {inv.invoice_number}",
                    description=msme_result["explanation"],
                    suggested_action="Process payment immediately. Calculate interest under Section 16 MSMED Act.",
                    invoice_id=inv.id,
                    evidence={
                        "invoice_number": inv.invoice_number,
                        "invoice_date": str(inv.invoice_date),
                        "acceptance_date": str(inv.acceptance_date) if inv.acceptance_date else None,
                        "payment_date": str(full_payment_date_msme) if full_payment_date_msme else "partial or pending",
                        "paid_amount": str(paid_msme),
                        "invoice_amount": str(inv.total_amount),
                        "days_taken": msme_result.get("days_taken"),
                        "msme_type": vendor.msme_type,
                        "udyam_number": vendor.udyam_number,
                    },
                    missing_information=msme_result.get("missing_evidence"),
                    amount_at_stake=(max(inv.total_amount - paid_msme, Decimal("0"))
                                     if paid_msme < inv.total_amount else inv.total_amount),
                )
                exceptions.append(exc)
                risk_score += SCORE_WEIGHTS["high"]

    if hr_foreign and not invoices:
        exc = _add_exception(db, vendor_id, "TDS_FOREIGN_REVIEW_EVIDENCE_MISSING", "tds", "medium",
            "Foreign vendor document requires tax-team review",
            "The supplied invoice identifies a foreign supplier, but it does not establish payment, tax residency, treaty eligibility or withholding treatment.",
            "Have the tax team assess the payment facts and applicable approved rules, then attach supporting tax-residency and payment evidence.",
            missing_information=["Payment/credit evidence", "Tax residency and treaty documentation", "Approved cross-border tax determination"],
            evidence={"vendor_name": vendor.legal_name, "source_currency": "Review the linked source document"})
        exceptions.append(exc)
        risk_score += SCORE_WEIGHTS["medium"]

    # -----------------------------------------------------------------------
    # 3. TDS three-way reconciliation (at vendor level for outstanding deductions)
    # -----------------------------------------------------------------------
    tds_invoices = [inv for inv in invoices if inv.tds_deducted_amount > Decimal("0")]
    if tds_invoices:
        total_deducted = sum(inv.tds_deducted_amount for inv in tds_invoices)

        # Reconcile deducted → linked government challans → reported return.
        if vendor.pan:
            returns = db.query(TDSReturnRecord).filter_by(deductee_pan=vendor.pan).all()
            total_reported = sum(r.tax_deducted for r in returns)
            challan_numbers = [r.challan_no for r in returns if r.challan_no]
            challans = db.query(TDSChallan).filter(TDSChallan.challan_no.in_(challan_numbers)).all() if challan_numbers else []
            total_deposited = sum((c.tax_amount for c in challans), Decimal("0"))

            if not challans:
                exc = _add_exception(db, vendor_id, "TDS_DEPOSIT_EVIDENCE_MISSING", "tds", "medium",
                    "TDS deposit evidence is missing", "No government challan could be linked to this vendor's reported TDS records.",
                    "Provide challan records and link each return line to its challan.",
                    missing_information=["Linked ITNS 281 challan evidence"],
                    evidence={"return_lines": len(returns), "challan_references": challan_numbers})
                exceptions.append(exc)
                risk_score += SCORE_WEIGHTS["medium"]

            recon = three_way_tds_reconciliation(total_deducted, total_deposited, total_reported)
            for issue in recon.get("issues", []):
                exc = _add_exception(
                    db, vendor_id,
                    check_code=f"TDS_{issue['type'].upper()}",
                    category="tds",
                    severity=issue["severity"],
                    title=f"TDS reconciliation issue: {issue['type']}",
                    description=issue["description"],
                    suggested_action="Verify Form 26Q/27Q filing and challan payments.",
                    evidence={
                        "tds_deducted": str(total_deducted),
                        "tds_deposited": str(total_deposited),
                        "tds_reported": str(total_reported),
                        "challan_count": len(challans),
                        "return_line_count": len(returns),
                    },
                    amount_at_stake=Decimal(issue.get("amount_at_stake", "0")),
                )
                exceptions.append(exc)
                risk_score += SCORE_WEIGHTS[issue["severity"]]

    # -----------------------------------------------------------------------
    # 4. Compute scorecard
    # -----------------------------------------------------------------------
    risk_score = min(risk_score, 100)

    if risk_score > SCORE_THRESHOLDS["needs_attention"]:
        status = ComplianceStatus.HIGH_RISK
        gst_status = tds_status = msme_status = "high_risk"
    elif exceptions or risk_score > SCORE_THRESHOLDS["compliant"]:
        # A low numeric score cannot override open evidence gaps or findings.
        # Reserve "compliant" for vendors with no recorded exceptions.
        status = ComplianceStatus.NEEDS_ATTENTION
        gst_status = tds_status = msme_status = "needs_attention"
    else:
        status = ComplianceStatus.COMPLIANT
        gst_status = tds_status = msme_status = "compliant"

    # Per-category status
    gst_excs = [e for e in exceptions if e.category == "gst"]
    tds_excs = [e for e in exceptions if e.category == "tds"]
    msme_excs = [e for e in exceptions if e.category == "msme"]
    master_excs = [e for e in exceptions if e.category == "master_data"]

    def _cat_status(excs):
        if not excs:
            return "compliant"
        if any(e.severity == "high" for e in excs):
            return "high_risk"
        return "needs_attention"

    gst_status = _cat_status(gst_excs)
    tds_status = _cat_status(tds_excs)
    msme_status = _cat_status(msme_excs)
    master_data_status = _cat_status(master_excs)

    # Total amount at stake at vendor level (unique per check_code + invoice)
    # Prevent double-counting: sum from exceptions, one entry per exception record
    invoice_exposure: Dict[str, Decimal] = {}
    master_exposure = Decimal("0")
    for exc in exceptions:
        amount = exc.amount_at_stake or Decimal("0")
        if exc.invoice_id:
            invoice_exposure[exc.invoice_id] = max(invoice_exposure.get(exc.invoice_id, Decimal("0")), amount)
        else:
            master_exposure += amount
    total_at_stake = sum(invoice_exposure.values(), master_exposure)

    summary_reasons = [
        f"{e.check_code}: {e.title}" for e in exceptions[:10]  # top 10
    ]
    recommended_actions = list({e.suggested_action for e in exceptions})[: 5]

    scorecard = VendorScorecard(
        id=_gen_id(),
        vendor_id=vendor_id,
        status=status,
        risk_score=risk_score,
        gst_status=gst_status,
        tds_status=tds_status,
        msme_status=msme_status,
        master_data_status=master_data_status,
        total_amount_at_stake=total_at_stake,
        currency="INR",
        summary_reasons=summary_reasons,
        evidence_coverage={
            "invoices_checked": len(invoices),
            "source_documents": db.query(VendorSourceDocument).filter_by(vendor_id=vendor_id).count(),
            "gst_exceptions": len(gst_excs),
            "tds_exceptions": len(tds_excs),
            "msme_exceptions": len(msme_excs),
            "master_data_exceptions": len(master_excs),
            "gstr2b_records_available": len(gstr2b_records),
            "amount_at_stake_available": any(e.amount_at_stake is not None for e in exceptions),
        },
        recommended_actions=recommended_actions,
        last_assessed_at=datetime.now(timezone.utc),
    )
    db.add(scorecard)
    db.flush()

    return scorecard


def run_all_vendors(db: Session) -> Dict:
    """Run compliance checks for all vendors. Returns summary."""
    vendors = db.query(VendorMaster).all()
    results = {"total": len(vendors), "completed": 0, "errors": []}
    for vendor in vendors:
        try:
            run_vendor_compliance_checks(db, vendor.id)
            results["completed"] += 1
        except Exception as exc:
            results["errors"].append({"vendor_id": vendor.id, "error": str(exc)})
    db.commit()
    return results
