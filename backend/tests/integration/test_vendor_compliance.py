"""Regression coverage for the synthetic vendor compliance workflow."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.vendor_compliance import (
    GSTR2BRecord, TDSChallan, VendorComplianceException, VendorMaster,
    VendorPayment, VendorScorecard,
)
from app.services.vendor_compliance.compliance_engine import run_vendor_compliance_checks
from app.services.vendor_compliance.gst_checks import check_gstr2b_match
from app.services.vendor_compliance.msme_checks import check_msme_payment_deadline
from app.services.vendor_compliance.synthetic_data import (
    EXPECTED_OUTCOMES, seed_vendor_compliance_data,
)
from app.services.vendor_compliance.tds_checks import compute_expected_tds
from app.api.v1.routers.vendor_compliance import (
    list_exceptions, list_master_cleanup, list_scorecards, scan_vendor_master,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_gstr2b_distinguishes_unavailable_from_confirmed_missing():
    assert check_gstr2b_match("INV-1", "27ABCDE1234F1Z5", "092026", []) == (
        "data_unavailable",
        "No GSTR-2B evidence is available for supplier 27ABCDE1234F1Z5 in period 092026; absence cannot be confirmed.",
    )
    evidence = [{
        "invoice_number": "OTHER-INV", "gstin_supplier": "27ABCDE1234F1Z5",
        "return_period": "092026",
    }]
    assert check_gstr2b_match("INV-1", "27ABCDE1234F1Z5", "092026", evidence)[0] == "missing"
    assert check_gstr2b_match("OTHER-INV", "27ABCDE1234F1Z5", "092026", evidence)[0] == "matched"


def test_seeded_scenarios_have_truthful_expected_scorecards_and_gstr_evidence(db):
    counts = seed_vendor_compliance_data(db)
    vendors = {v.vendor_code: v for v in db.query(VendorMaster).all()}
    assert counts["vendors"] == len(EXPECTED_OUTCOMES)
    assert all(v.is_synthetic for v in vendors.values())

    cards = {}
    exceptions_by_vendor = {}
    for code, vendor in vendors.items():
        card = run_vendor_compliance_checks(db, vendor.id)
        cards[code] = card
        exceptions_by_vendor[code] = {
            e.check_code for e in db.query(VendorComplianceException).filter_by(vendor_id=vendor.id).all()
        }

    for code, expected in EXPECTED_OUTCOMES.items():
        assert cards[code].status == expected["status"], code
        assert set(expected["expected_exceptions"]).issubset(exceptions_by_vendor[code]), code

    # A return period with source rows but without this invoice is a mismatch.
    assert "GST_GSTR2B_MISSING" in exceptions_by_vendor["VENDOR_GSTR2B_MISSING_001"]
    # Exact day 45 remains compliant when the invoice has matching evidence.
    assert cards["VENDOR_MSME_EXACT_45_001"].status == "compliant"


def test_seed_repairs_supplemental_demo_evidence_without_duplicates(db):
    seed_vendor_compliance_data(db)
    seed_vendor_compliance_data(db)
    assert db.query(GSTR2BRecord).filter_by(
        gstin_supplier="07AAFMG3456I1ZQ", return_period="092026"
    ).count() == 1
    assert db.query(GSTR2BRecord).filter_by(
        gstin_supplier="24AAJEB1122L1ZT", invoice_number="EBM/2026/001"
    ).count() == 1
    assert db.query(TDSChallan).filter_by(challan_no="SYNTH-CHALLAN-CTS-001").count() == 1


def test_gstr2b_unloaded_period_creates_explicit_evidence_exception(db):
    seed_vendor_compliance_data(db)
    vendor = db.query(VendorMaster).filter_by(vendor_code="VENDOR_GSTR2B_MISSING_001").one()
    db.query(GSTR2BRecord).filter_by(gstin_supplier=vendor.gstin).delete()
    run_vendor_compliance_checks(db, vendor.id)
    exception = db.query(VendorComplianceException).filter_by(
        vendor_id=vendor.id, check_code="GST_GSTR2B_EVIDENCE_UNAVAILABLE"
    ).one()
    assert exception.missing_information == ["GSTR-2B source evidence for return period 092026"]
    assert exception.evidence["match_status"] == "data_unavailable"


def test_tds_threshold_edges_and_missing_challan_are_reported(db):
    below, required, _ = compute_expected_tds(
        Decimal("29999.99"), Decimal("10"), Decimal("30000")
    )
    at_threshold, required_at_threshold, _ = compute_expected_tds(
        Decimal("30000"), Decimal("10"), Decimal("30000")
    )
    assert below == Decimal("0") and required is False
    assert at_threshold == Decimal("3000.00") and required_at_threshold is True

    seed_vendor_compliance_data(db)
    vendor = db.query(VendorMaster).filter_by(vendor_code="VENDOR_COMPLIANT_001").one()
    db.query(TDSChallan).delete()
    run_vendor_compliance_checks(db, vendor.id)
    exception = db.query(VendorComplianceException).filter_by(
        vendor_id=vendor.id, check_code="TDS_DEPOSIT_EVIDENCE_MISSING"
    ).one()
    assert exception.missing_information == ["Linked ITNS 281 challan evidence"]


def test_foreign_vendor_missing_documents_are_unverified_evidence(db):
    seed_vendor_compliance_data(db)
    vendor = db.query(VendorMaster).filter_by(vendor_code="VENDOR_FOREIGN_001").one()
    run_vendor_compliance_checks(db, vendor.id)
    exception = db.query(VendorComplianceException).filter_by(
        vendor_id=vendor.id, check_code="TDS_FOREIGN_DOCUMENTATION_UNCONFIRMED"
    ).one()
    assert exception.missing_information
    assert exception.amount_at_stake is None
    assert "no threshold" in exception.description.lower()


def test_msme_exact_45_day_boundary_and_partial_balance(db):
    start = date(2026, 9, 1)
    exact = check_msme_payment_deadline(
        invoice_date=start, acceptance_date=None, payment_date=start + timedelta(days=45),
        msme_type="micro", udyam_number="UDYAM-GJ-04-0004567", is_msme_verified=True,
        paid_amount=Decimal("100"), invoice_amount=Decimal("100"),
    )
    assert exact["status"] == "compliant" and exact["is_flagged"] is False

    seed_vendor_compliance_data(db)
    vendor = db.query(VendorMaster).filter_by(vendor_code="VENDOR_MSME_BREACH_001").one()
    payment = db.query(VendorPayment).filter_by(vendor_id=vendor.id).one()
    payment.gross_amount_paid = Decimal("100000.00")
    payment.net_amount_paid = Decimal("96000.00")
    run_vendor_compliance_checks(db, vendor.id)
    exception = db.query(VendorComplianceException).filter_by(
        vendor_id=vendor.id, check_code="MSME_45_DAY_BREACH"
    ).one()
    assert exception.amount_at_stake == Decimal("136000.00")
    assert exception.evidence["paid_amount"] == "100000.00"


def test_scorecard_exception_and_cleanup_deliverables_are_available(db):
    seed_vendor_compliance_data(db)
    for vendor in db.query(VendorMaster).all():
        run_vendor_compliance_checks(db, vendor.id)
    db.commit()

    scorecards = list_scorecards(db=db)
    exceptions = list_exceptions(db=db)
    cleanup_created = scan_vendor_master(db=db)
    cleanup_list = list_master_cleanup(db=db)

    assert scorecards and len(scorecards) == db.query(VendorScorecard).count()
    assert exceptions and all("suggested_action" in e for e in exceptions)
    assert all("amount_at_stake" in e and "currency" in e for e in exceptions)
    assert cleanup_created and cleanup_list
