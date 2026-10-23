"""
Synthetic vendor compliance dataset for testing and demonstration.

All records are clearly marked as synthetic (is_synthetic=True).
Expected compliance outcomes are documented in EXPECTED_OUTCOMES below.
This data must NOT be used for actual compliance decisions.

Dataset includes:
- Valid cases (compliant vendors)
- Invalid cases (GSTIN format errors, PAN mismatches)
- GSTR-2B mismatches
- TDS calculation errors
- MSME 45-day breaches
- ITC 180-day reversals
- Blocked ITC cases
- Foreign vendor without 15CA/15CB
- Boundary cases (exactly at 45-day and 180-day limits)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List

from sqlalchemy.orm import Session

from app.models.vendor_compliance import (
    VendorMaster, VendorInvoice, VendorPayment,
    GSTR2BRecord, TDSChallan, TDSReturnRecord, TaxRule,
)


def _id() -> str:
    return str(uuid.uuid4())


# Expected outcomes for test verification (documented ground truth)
EXPECTED_OUTCOMES = {
    "VENDOR_COMPLIANT_001": {
        "status": "compliant",
        "expected_exceptions": [],
        "notes": "All data valid, payment within 45 days, TDS correct",
    },
    "VENDOR_GSTIN_BAD_001": {
        "status": "high_risk",
        "expected_exceptions": ["MASTER_GSTIN_FORMAT"],
        "notes": "GSTIN is 12 chars instead of 15",
    },
    "VENDOR_PAN_MISMATCH_001": {
        "status": "high_risk",
        "expected_exceptions": ["MASTER_PAN_GSTIN_MISMATCH"],
        "notes": "PAN does not match GSTIN-embedded PAN",
    },
    "VENDOR_MSME_BREACH_001": {
        "status": "high_risk",
        "expected_exceptions": ["MSME_45_DAY_BREACH"],
        "notes": "Payment made 60 days after invoice — MSME breach",
    },
    "VENDOR_ITC_REVERSAL_001": {
        "status": "high_risk",
        "expected_exceptions": ["GST_ITC_180_DAY"],
        "notes": "Payment after 180 days — ITC must be reversed",
    },
    "VENDOR_GSTR2B_MISSING_001": {
        "status": "needs_attention",
        "expected_exceptions": ["GST_GSTR2B_MISSING"],
        "notes": "Invoice not in GSTR-2B",
    },
    "VENDOR_TDS_SHORT_001": {
        "status": "high_risk",
        "expected_exceptions": ["TDS_DEDUCTION_MISMATCH"],
        "notes": "TDS deducted at 1% instead of 10% under 194J",
    },
    "VENDOR_BLOCKED_ITC_001": {
        "status": "high_risk",
        "expected_exceptions": ["GST_BLOCKED_ITC"],
        "notes": "Invoice is for food/beverage — ITC blocked under 17(5)",
    },
    "VENDOR_FOREIGN_001": {
        "status": "high_risk",
        "expected_exceptions": ["TDS_FOREIGN_MISSING_15CA_15CB"],
        "notes": "Foreign vendor large payment without Form 15CA/15CB",
    },
    "VENDOR_MSME_EXACT_45_001": {
        "status": "compliant",
        "expected_exceptions": [],
        "notes": "Payment exactly on day 45 — boundary case, compliant",
    },
}


def seed_vendor_compliance_data(db: Session) -> dict:
    """
    Create synthetic vendor compliance dataset.
    Safe to re-run: skips if vendor_code already exists.
    Returns count of created records.
    """
    counts = {"vendors": 0, "invoices": 0, "payments": 0, "gstr2b": 0, "challans": 0, "returns": 0}

    # -----------------------------------------------------------------------
    # VENDOR_COMPLIANT_001 — everything correct
    # -----------------------------------------------------------------------
    v1_code = "VENDOR_COMPLIANT_001"
    if not db.query(VendorMaster).filter_by(vendor_code=v1_code).first():
        v1 = VendorMaster(
            id=_id(), vendor_code=v1_code,
            legal_name="Compliant Tech Solutions Pvt Ltd",
            pan="AABCC1234D", is_pan_verified=True, pan_operative_status="OPERATIVE",
            gstin="27AABCC1234D1ZR", is_gstin_verified=True, gstin_status="ACTIVE",
            state_code="27", vendor_type="domestic", country="IN",
            msme_type="non_msme", payment_terms_days=30, is_synthetic=True,
        )
        db.add(v1); db.flush(); counts["vendors"] += 1

        inv1 = VendorInvoice(
            id=_id(), vendor_id=v1.id, invoice_number="CTS/2026/001",
            invoice_date=date(2026, 9, 1), financial_year="2026-27",
            supply_type="intra_state", pos_state_code="27", recipient_state_code="27",
            hsn_sac_code="9983", description="Software development services",
            is_rcm=False, is_blocked_itc_17_5=False,
            taxable_amount=Decimal("100000.00"),
            cgst_amount=Decimal("9000.00"), sgst_amount=Decimal("9000.00"), igst_amount=Decimal("0.00"),
            total_tax_amount=Decimal("18000.00"), total_amount=Decimal("118000.00"),
            tds_section="194J", tds_rate_pct=Decimal("10.00"),
            tds_base_amount=Decimal("100000.00"), tds_deducted_amount=Decimal("10000.00"),
            is_synthetic=True,
        )
        db.add(inv1); db.flush(); counts["invoices"] += 1

        p1 = VendorPayment(
            id=_id(), vendor_id=v1.id, invoice_id=inv1.id,
            payment_reference="PAY_CTS_001", payment_date=date(2026, 9, 25),
            gross_amount_paid=Decimal("118000.00"),
            tds_deducted_at_payment=Decimal("10000.00"),
            net_amount_paid=Decimal("108000.00"), is_synthetic=True,
        )
        db.add(p1); counts["payments"] += 1

        g1 = GSTR2BRecord(
            id=_id(), gstin_supplier="27AABCC1234D1ZR",
            invoice_number="CTS/2026/001", invoice_date=date(2026, 9, 1),
            taxable_value=Decimal("100000.00"), cgst=Decimal("9000.00"),
            sgst=Decimal("9000.00"), igst=Decimal("0.00"), itc_availability="Y",
            return_period="092026", is_synthetic=True,
        )
        db.add(g1); counts["gstr2b"] += 1

        ret1 = TDSReturnRecord(
            id=_id(), form_type="26Q", quarter="Q2", financial_year="2026-27",
            deductee_pan="AABCC1234D", invoice_number="CTS/2026/001",
            section_code="194J", amount_paid=Decimal("100000.00"),
            tax_deducted=Decimal("10000.00"), tax_deposited=Decimal("10000.00"),
            is_synthetic=True,
        )
        db.add(ret1); counts["returns"] += 1

    # -----------------------------------------------------------------------
    # VENDOR_GSTIN_BAD_001 — invalid GSTIN (too short)
    # -----------------------------------------------------------------------
    v2_code = "VENDOR_GSTIN_BAD_001"
    if not db.query(VendorMaster).filter_by(vendor_code=v2_code).first():
        v2 = VendorMaster(
            id=_id(), vendor_code=v2_code,
            legal_name="Bad GSTIN Enterprises",
            pan="BBGST5678E", is_pan_verified=False,
            gstin="27BBGST5678E",  # Only 12 chars — invalid
            is_gstin_verified=False, gstin_status="ACTIVE",
            state_code="27", vendor_type="domestic", country="IN",
            msme_type="non_msme", payment_terms_days=30, is_synthetic=True,
        )
        db.add(v2); db.flush(); counts["vendors"] += 1

        inv2 = VendorInvoice(
            id=_id(), vendor_id=v2.id, invoice_number="BGE/2026/001",
            invoice_date=date(2026, 9, 5), financial_year="2026-27",
            supply_type="intra_state", pos_state_code="27", recipient_state_code="27",
            taxable_amount=Decimal("50000.00"),
            cgst_amount=Decimal("4500.00"), sgst_amount=Decimal("4500.00"), igst_amount=Decimal("0.00"),
            total_tax_amount=Decimal("9000.00"), total_amount=Decimal("59000.00"),
            tds_deducted_amount=Decimal("0.00"), is_synthetic=True,
        )
        db.add(inv2); db.flush(); counts["invoices"] += 1

    # -----------------------------------------------------------------------
    # VENDOR_PAN_MISMATCH_001 — PAN doesn't match GSTIN
    # -----------------------------------------------------------------------
    v3_code = "VENDOR_PAN_MISMATCH_001"
    if not db.query(VendorMaster).filter_by(vendor_code=v3_code).first():
        v3 = VendorMaster(
            id=_id(), vendor_code=v3_code,
            legal_name="PAN Mismatch Trading Co",
            pan="WRONGPAN9X",  # Does not match GSTIN-embedded PAN
            is_pan_verified=False,
            gstin="27AABPM5678F1Z5",  # Embeds PAN AABPM5678F
            is_gstin_verified=True, gstin_status="ACTIVE",
            state_code="27", vendor_type="domestic", country="IN",
            msme_type="non_msme", payment_terms_days=30, is_synthetic=True,
        )
        db.add(v3); db.flush(); counts["vendors"] += 1

    # -----------------------------------------------------------------------
    # VENDOR_MSME_BREACH_001 — MSME 45-day breach (60-day payment)
    # -----------------------------------------------------------------------
    v4_code = "VENDOR_MSME_BREACH_001"
    if not db.query(VendorMaster).filter_by(vendor_code=v4_code).first():
        v4 = VendorMaster(
            id=_id(), vendor_code=v4_code,
            legal_name="Small Vendor MSME Services",
            pan="AACMB4567G", is_pan_verified=True,
            gstin="29AACMB4567G1ZV", is_gstin_verified=True, gstin_status="ACTIVE",
            state_code="29", vendor_type="domestic", country="IN",
            msme_type="small", udyam_number="UDYAM-KA-07-0001234",
            is_msme_verified=True, payment_terms_days=30, is_synthetic=True,
        )
        db.add(v4); db.flush(); counts["vendors"] += 1

        inv4 = VendorInvoice(
            id=_id(), vendor_id=v4.id, invoice_number="MSME/2026/001",
            invoice_date=date(2026, 8, 1), financial_year="2026-27",
            supply_type="inter_state", pos_state_code="27", recipient_state_code="29",
            taxable_amount=Decimal("200000.00"),
            cgst_amount=Decimal("0.00"), sgst_amount=Decimal("0.00"), igst_amount=Decimal("36000.00"),
            total_tax_amount=Decimal("36000.00"), total_amount=Decimal("236000.00"),
            tds_section="194C", tds_deducted_amount=Decimal("4000.00"), is_synthetic=True,
        )
        db.add(inv4); db.flush(); counts["invoices"] += 1

        # Payment on day 60 — breach of 45-day rule
        p4 = VendorPayment(
            id=_id(), vendor_id=v4.id, invoice_id=inv4.id,
            payment_reference="PAY_MSME_001", payment_date=date(2026, 9, 30),  # 60 days
            gross_amount_paid=Decimal("236000.00"),
            tds_deducted_at_payment=Decimal("4000.00"),
            net_amount_paid=Decimal("232000.00"), is_synthetic=True,
        )
        db.add(p4); counts["payments"] += 1

    # -----------------------------------------------------------------------
    # VENDOR_ITC_REVERSAL_001 — ITC 180-day rule breach
    # -----------------------------------------------------------------------
    v5_code = "VENDOR_ITC_REVERSAL_001"
    if not db.query(VendorMaster).filter_by(vendor_code=v5_code).first():
        v5 = VendorMaster(
            id=_id(), vendor_code=v5_code,
            legal_name="Late Payment Corp",
            pan="AADLP9012H", is_pan_verified=True,
            gstin="19AADLP9012H1ZF", is_gstin_verified=True, gstin_status="ACTIVE",
            state_code="19", vendor_type="domestic", country="IN",
            msme_type="non_msme", payment_terms_days=60, is_synthetic=True,
        )
        db.add(v5); db.flush(); counts["vendors"] += 1

        inv5 = VendorInvoice(
            id=_id(), vendor_id=v5.id, invoice_number="LPC/2026/001",
            invoice_date=date(2026, 3, 1), financial_year="2026-27",
            supply_type="intra_state", pos_state_code="19", recipient_state_code="19",
            taxable_amount=Decimal("500000.00"),
            cgst_amount=Decimal("45000.00"), sgst_amount=Decimal("45000.00"), igst_amount=Decimal("0.00"),
            total_tax_amount=Decimal("90000.00"), total_amount=Decimal("590000.00"),
            tds_deducted_amount=Decimal("0.00"), is_synthetic=True,
        )
        db.add(inv5); db.flush(); counts["invoices"] += 1

        # Payment after 200 days — ITC reversal required (>180 days)
        p5 = VendorPayment(
            id=_id(), vendor_id=v5.id, invoice_id=inv5.id,
            payment_reference="PAY_LPC_001", payment_date=date(2026, 9, 17),  # 200 days
            gross_amount_paid=Decimal("590000.00"), tds_deducted_at_payment=Decimal("0.00"),
            net_amount_paid=Decimal("590000.00"), is_synthetic=True,
        )
        db.add(p5); counts["payments"] += 1

    # -----------------------------------------------------------------------
    # VENDOR_GSTR2B_MISSING_001 — invoice not in GSTR-2B
    # -----------------------------------------------------------------------
    v6_code = "VENDOR_GSTR2B_MISSING_001"
    if not db.query(VendorMaster).filter_by(vendor_code=v6_code).first():
        v6 = VendorMaster(
            id=_id(), vendor_code=v6_code,
            legal_name="Missing GSTR Suppliers Ltd",
            pan="AAFMG3456I", is_pan_verified=True,
            gstin="07AAFMG3456I1ZQ", is_gstin_verified=True, gstin_status="ACTIVE",
            state_code="07", vendor_type="domestic", country="IN",
            msme_type="non_msme", payment_terms_days=30, is_synthetic=True,
        )
        db.add(v6); db.flush(); counts["vendors"] += 1

        inv6 = VendorInvoice(
            id=_id(), vendor_id=v6.id, invoice_number="MGS/2026/001",
            invoice_date=date(2026, 9, 10), financial_year="2026-27",
            supply_type="intra_state", pos_state_code="07", recipient_state_code="07",
            taxable_amount=Decimal("80000.00"),
            cgst_amount=Decimal("7200.00"), sgst_amount=Decimal("7200.00"), igst_amount=Decimal("0.00"),
            total_tax_amount=Decimal("14400.00"), total_amount=Decimal("94400.00"),
            tds_deducted_amount=Decimal("0.00"), is_synthetic=True,
        )
        db.add(inv6); db.flush(); counts["invoices"] += 1
        # NO GSTR2B record added — this will trigger the missing check

        p6 = VendorPayment(
            id=_id(), vendor_id=v6.id, invoice_id=inv6.id,
            payment_reference="PAY_MGS_001", payment_date=date(2026, 10, 5),
            gross_amount_paid=Decimal("94400.00"), tds_deducted_at_payment=Decimal("0.00"),
            net_amount_paid=Decimal("94400.00"), is_synthetic=True,
        )
        db.add(p6); counts["payments"] += 1

    # -----------------------------------------------------------------------
    # VENDOR_TDS_SHORT_001 — TDS deducted at wrong rate (1% instead of 10%)
    # -----------------------------------------------------------------------
    v7_code = "VENDOR_TDS_SHORT_001"
    if not db.query(VendorMaster).filter_by(vendor_code=v7_code).first():
        v7 = VendorMaster(
            id=_id(), vendor_code=v7_code,
            legal_name="Consulting Partners LLP",
            pan="AAGCP7890J", is_pan_verified=True,
            gstin="09AAGCP7890J1ZD", is_gstin_verified=True, gstin_status="ACTIVE",
            state_code="09", vendor_type="domestic", country="IN",
            msme_type="non_msme", payment_terms_days=30, is_synthetic=True,
        )
        db.add(v7); db.flush(); counts["vendors"] += 1

        inv7 = VendorInvoice(
            id=_id(), vendor_id=v7.id, invoice_number="CPL/2026/001",
            invoice_date=date(2026, 9, 15), financial_year="2026-27",
            supply_type="intra_state", pos_state_code="09", recipient_state_code="09",
            taxable_amount=Decimal("300000.00"),
            cgst_amount=Decimal("27000.00"), sgst_amount=Decimal("27000.00"), igst_amount=Decimal("0.00"),
            total_tax_amount=Decimal("54000.00"), total_amount=Decimal("354000.00"),
            tds_section="194J",  # Professional fees — 10% rate
            tds_rate_pct=Decimal("10.00"),
            tds_base_amount=Decimal("300000.00"),
            tds_deducted_amount=Decimal("3000.00"),  # WRONG: deducted 1% not 10% (should be 30000)
            is_synthetic=True,
        )
        db.add(inv7); db.flush(); counts["invoices"] += 1

    # -----------------------------------------------------------------------
    # VENDOR_BLOCKED_ITC_001 — food/beverage — blocked ITC
    # -----------------------------------------------------------------------
    v8_code = "VENDOR_BLOCKED_ITC_001"
    if not db.query(VendorMaster).filter_by(vendor_code=v8_code).first():
        v8 = VendorMaster(
            id=_id(), vendor_code=v8_code,
            legal_name="Canteen Supplies Pvt Ltd",
            pan="AAHCS2345K", is_pan_verified=True,
            gstin="33AAHCS2345K1ZC", is_gstin_verified=True, gstin_status="ACTIVE",
            state_code="33", vendor_type="domestic", country="IN",
            msme_type="non_msme", payment_terms_days=30, is_synthetic=True,
        )
        db.add(v8); db.flush(); counts["vendors"] += 1

        inv8 = VendorInvoice(
            id=_id(), vendor_id=v8.id, invoice_number="CS/2026/001",
            invoice_date=date(2026, 9, 20), financial_year="2026-27",
            supply_type="intra_state", pos_state_code="33", recipient_state_code="33",
            taxable_amount=Decimal("50000.00"),
            cgst_amount=Decimal("2500.00"), sgst_amount=Decimal("2500.00"), igst_amount=Decimal("0.00"),
            total_tax_amount=Decimal("5000.00"), total_amount=Decimal("55000.00"),
            is_blocked_itc_17_5=True, blocked_itc_category="food_beverage",
            tds_deducted_amount=Decimal("0.00"), is_synthetic=True,
        )
        db.add(inv8); db.flush(); counts["invoices"] += 1

    # -----------------------------------------------------------------------
    # VENDOR_FOREIGN_001 — foreign vendor, large payment, no 15CA/15CB
    # -----------------------------------------------------------------------
    v9_code = "VENDOR_FOREIGN_001"
    if not db.query(VendorMaster).filter_by(vendor_code=v9_code).first():
        v9 = VendorMaster(
            id=_id(), vendor_code=v9_code,
            legal_name="Foreign Cloud Services Inc",
            pan=None, is_pan_verified=False,  # Foreign vendor may not have Indian PAN
            gstin=None, is_gstin_verified=False,
            vendor_type="foreign", country="US",
            msme_type="non_msme", payment_terms_days=30, is_synthetic=True,
        )
        db.add(v9); db.flush(); counts["vendors"] += 1

        inv9 = VendorInvoice(
            id=_id(), vendor_id=v9.id, invoice_number="FCS/2026/001",
            invoice_date=date(2026, 9, 1), financial_year="2026-27",
            supply_type="inter_state",  # Cross-border
            pos_state_code="00", recipient_state_code="27",
            taxable_amount=Decimal("6000000.00"),  # INR 60L — requires 15CA/15CB
            cgst_amount=Decimal("0.00"), sgst_amount=Decimal("0.00"), igst_amount=Decimal("0.00"),
            total_tax_amount=Decimal("0.00"), total_amount=Decimal("6000000.00"),
            tds_section="195",  # Foreign payment section
            tds_deducted_amount=Decimal("1200000.00"),  # 20% illustrative
            has_form_15ca_15cb=False,  # MISSING — exception should be raised
            is_synthetic=True,
        )
        db.add(inv9); db.flush(); counts["invoices"] += 1

    # -----------------------------------------------------------------------
    # VENDOR_MSME_EXACT_45_001 — boundary: paid exactly on day 45 (compliant)
    # -----------------------------------------------------------------------
    v10_code = "VENDOR_MSME_EXACT_45_001"
    if not db.query(VendorMaster).filter_by(vendor_code=v10_code).first():
        v10 = VendorMaster(
            id=_id(), vendor_code=v10_code,
            legal_name="Exact Boundary MSME Ltd",
            pan="AAJEB1122L", is_pan_verified=True,
            gstin="24AAJEB1122L1ZT", is_gstin_verified=True, gstin_status="ACTIVE",
            state_code="24", vendor_type="domestic", country="IN",
            msme_type="micro", udyam_number="UDYAM-GJ-04-0004567",
            is_msme_verified=True, payment_terms_days=45, is_synthetic=True,
        )
        db.add(v10); db.flush(); counts["vendors"] += 1

        inv10 = VendorInvoice(
            id=_id(), vendor_id=v10.id, invoice_number="EBM/2026/001",
            invoice_date=date(2026, 9, 1), financial_year="2026-27",
            supply_type="intra_state", pos_state_code="24", recipient_state_code="24",
            taxable_amount=Decimal("25000.00"),
            cgst_amount=Decimal("2250.00"), sgst_amount=Decimal("2250.00"), igst_amount=Decimal("0.00"),
            total_tax_amount=Decimal("4500.00"), total_amount=Decimal("29500.00"),
            tds_deducted_amount=Decimal("0.00"), is_synthetic=True,
        )
        db.add(inv10); db.flush(); counts["invoices"] += 1

        # Exactly day 45 — compliant
        p10 = VendorPayment(
            id=_id(), vendor_id=v10.id, invoice_id=inv10.id,
            payment_reference="PAY_EBM_001", payment_date=date(2026, 10, 16),  # day 45
            gross_amount_paid=Decimal("29500.00"), tds_deducted_at_payment=Decimal("0.00"),
            net_amount_paid=Decimal("29500.00"), is_synthetic=True,
        )
        db.add(p10); counts["payments"] += 1

    # -----------------------------------------------------------------------
    # Sample TDS rules (clearly marked illustrative)
    # -----------------------------------------------------------------------
    from app.services.vendor_compliance.tds_checks import SAMPLE_TDS_RULES
    for r in SAMPLE_TDS_RULES:
        exists = db.query(TaxRule).filter_by(rule_code=r["rule_code"]).first()
        if not exists:
            rule = TaxRule(
                id=_id(),
                rule_code=r["rule_code"],
                tax_category=r["tax_category"],
                section_1961=r.get("section_1961"),
                section_2025=r.get("section_2025"),
                description=r["description"],
                rate_pct=r["rate_pct"],
                threshold_amount=r["threshold_amount"],
                tax_base=r["tax_base"],
                effective_from=r["effective_from"],
                effective_to=r.get("effective_to"),
                source_reference=r.get("source_reference"),
                verification_status=r.get("verification_status", "pending_review"),
                is_sample_rule=True,
                version="1.0",
            )
            db.add(rule)

    db.commit()
    return counts
