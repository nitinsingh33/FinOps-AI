"""End-to-end service checks on an isolated SQLite database."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.models import (
    ExceptionCategory, GatewayTransaction, ImportJob, Payment, Refund,
    ReconciliationException, ReconciliationRun, SourceRecord, UploadedDataset,
    Settlement, PricingRule,
)
from app.models.vendor_compliance import VendorComplianceException, VendorMaster, VendorScorecard
from app.services.import_service import compute_sha256, register_dataset, create_import_job, run_import_job
from app.services.reconciliation.engine import run_reconciliation
from app.services.analytics_service import get_gateway_cost_analysis
from app.services.vendor_compliance.synthetic_data import seed_vendor_compliance_data
from app.services.vendor_compliance.compliance_engine import run_vendor_compliance_checks
from app.api.v1.routers.reports import download_payments_csv, executive_summary
from app.api.v1.routers.pricing import SavingsScenarioCreate, create_savings_scenario

ROOT = Path(__file__).resolve().parents[3]
WORKBOOKS = [
    ("gwa_payments", "GatewayA_payments_Sep26_dummy.xlsx"),
    ("gwa_transactions", "GatewayA_transactions_Sep26_dummy.xlsx"),
    ("gwa_refunds", "GatewayA_refunds_Sep26_dummy.xlsx"),
    ("gwb_balance", "GatewayB_Sep26_dummy.xlsx"),
]
EXPECTED_IMPORT_ROWS = {
    "gwa_payments": 475,
    "gwa_transactions": 414,
    "gwa_refunds": 13,
    "gwb_balance": 731,
}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_four_workbook_imports_and_retry_are_idempotent(db):
    first_pass = {}
    for dataset_type, filename in WORKBOOKS:
        path = ROOT / "data" / filename
        digest = compute_sha256(str(path))
        dataset, is_new = register_dataset(db, filename, dataset_type, str(path), path.stat().st_size, digest)
        assert is_new
        job = run_import_job(db, create_import_job(db, dataset.id).id)
        assert job.status in ("completed", "completed_with_warnings")
        assert job.total_rows == EXPECTED_IMPORT_ROWS[dataset_type]
        assert job.imported_rows == EXPECTED_IMPORT_ROWS[dataset_type]
        assert job.duplicate_count == 0
        assert job.warning_count == 0
        assert job.error_count == 0
        first_pass[dataset_type] = (job.imported_rows, job.duplicate_count, job.warning_count, job.error_count)

    db.commit()
    assert db.query(Payment).count() > 0
    assert db.query(GatewayTransaction).count() > 0
    assert db.query(Refund).count() > 0
    assert db.query(Settlement).filter_by(gateway="gateway_a").count() == 48
    assert db.query(Settlement).filter_by(gateway="gateway_b").count() == 35
    for payout in db.query(Settlement).filter_by(gateway="gateway_b"):
        payout_id, currency = payout.gateway_settlement_id.rsplit(":", 1)
        payout_rows = db.query(GatewayTransaction).filter_by(
            gateway="gateway_b", payout_id=payout_id, currency=currency
        ).all()
        expected_net = sum((row.net_amount for row in payout_rows if row.net_amount is not None), Decimal("0"))
        assert payout_rows and payout.net_amount == expected_net
    assert db.query(SourceRecord).count() == sum(row[0] for row in first_pass.values())

    monthly = get_gateway_cost_analysis(db)["monthly_breakdowns"]
    assert monthly
    assert all(len(row["month"]) == 7 for row in monthly)
    assert all(row["transaction_count"] > 0 for row in monthly)
    assert all(row["gross_volume"] >= 0 and row["observed_fees"] >= 0 for row in monthly)
    assert {row["gateway"] for row in monthly}.issubset({"gateway_a", "gateway_b"})

    for dataset_type, filename in WORKBOOKS:
        path = ROOT / "data" / filename
        dataset, is_new = register_dataset(db, filename, dataset_type, str(path), path.stat().st_size, compute_sha256(str(path)))
        assert not is_new
        retry = run_import_job(db, create_import_job(db, dataset.id).id)
        assert retry.imported_rows == 0
        assert retry.duplicate_count == first_pass[dataset_type][0] + first_pass[dataset_type][1]
        assert retry.error_count == first_pass[dataset_type][3]


def test_reconciliation_and_csv_export_use_imported_records(db):
    for dataset_type, filename in WORKBOOKS:
        path = ROOT / "data" / filename
        dataset, _ = register_dataset(db, filename, dataset_type, str(path), path.stat().st_size, compute_sha256(str(path)))
        run_import_job(db, create_import_job(db, dataset.id).id)
    run = ReconciliationRun(id="integration-run", status="pending")
    db.add(run)
    db.flush()
    result = run_reconciliation(db, run.id)
    db.commit()
    assert result.status == "completed"
    # Source rows across payments, Gateway A transactions, refunds, and
    # Gateway B balance transactions: 475 + 414 + 13 + 731.
    assert result.total_records == 1633
    assert result.matched_records > 0
    assert result.exception_count is not None
    persisted_exception_count = db.query(ReconciliationException).filter_by(run_id=run.id).count()
    assert result.exception_count == persisted_exception_count
    assert sum(result.summary["exception_by_category"].values()) == result.exception_count
    exposure = result.summary["amounts_at_stake_by_currency"]
    assert exposure and all(len(currency) == 3 for currency in exposure)

    response = download_payments_csv(gateway=None, currency=None, status=None, db=db)
    body = response.body.decode("utf-8")
    assert "gateway_payment_id" in body
    assert db.query(Payment).first().gateway_payment_id in body
    page = executive_summary(db=db).body.decode("utf-8")
    assert "Executive Summary" in page
    assert "Observed transaction volume" in page
    assert "contractual rates have not been independently verified" in page


def test_partial_refunds_are_aggregated_by_currency_and_ignore_failed_refunds(db):
    payment = Payment(
        id="partial-refund-payment", source_record_id="payment-source",
        gateway="gateway_a", gateway_payment_id="apay_partial", status="failed",
        gross_amount=Decimal("500.00"), currency="INR",
        amount_refunded=Decimal("100.00"),
    )
    db.add(payment)
    db.add_all([
        Refund(id="partial-refund-1", source_record_id="refund-source-1", gateway="gateway_a",
               gateway_refund_id="aref_1", gateway_payment_id="apay_partial", status="processed",
               amount=Decimal("40.00"), currency="INR"),
        Refund(id="partial-refund-2", source_record_id="refund-source-2", gateway="gateway_a",
               gateway_refund_id="aref_2", gateway_payment_id="apay_partial", status="processed",
               amount=Decimal("60.00"), currency="INR"),
        Refund(id="failed-refund", source_record_id="refund-source-3", gateway="gateway_a",
               gateway_refund_id="aref_failed", gateway_payment_id="apay_partial", status="failed",
               amount=Decimal("900.00"), currency="INR"),
        Refund(id="foreign-currency-refund", source_record_id="refund-source-4", gateway="gateway_a",
               gateway_refund_id="aref_usd", gateway_payment_id="apay_partial", status="processed",
               amount=Decimal("1.00"), currency="USD"),
    ])
    run = ReconciliationRun(id="partial-refund-run", status="pending")
    db.add(run)
    db.flush()
    run_reconciliation(db, run.id)
    mismatch_count = db.query(ReconciliationException).filter_by(
        run_id=run.id, category=ExceptionCategory.REFUND_AMOUNT_MISMATCH
    ).count()
    assert mismatch_count == 0


def test_pricing_scenario_rejects_currency_mismatch(db):
    current = PricingRule(id="price-a", gateway="gateway_a", rule_name="Observed INR input",
        currency="INR", fee_rate_pct=2, fixed_fee=5, fixed_fee_currency="INR",
        tax_on_fee_pct=18, is_illustrative=False, version="1")
    alternative = PricingRule(id="price-b", gateway="gateway_b", rule_name="USD input",
        currency="USD", fee_rate_pct=1.5, is_illustrative=True, version="1")
    db.add_all([current, alternative]); db.commit()
    result = create_savings_scenario(SavingsScenarioCreate(
        name="Currency validation", current_gateway="gateway_a", alternative_gateway="gateway_b",
        currency="INR", eligible_volume=1000, current_pricing_rule_id=current.id,
        alternative_pricing_rule_id=alternative.id,
    ), db=db)
    assert result["current_estimated_fee"] is not None
    assert result["alternative_estimated_fee"] is None
    assert any("currency" in item.lower() for item in result["limitations"])
    assert any("not independently verified" in item for item in result["limitations"])


def test_pricing_scenario_requires_rule_country_and_method_context(db):
    current = PricingRule(
        id="country-method-rule", gateway="gateway_a", rule_name="Illustrative IN card",
        currency="INR", country="IN", payment_method="card", fee_rate_pct=2,
        is_illustrative=True, version="1",
    )
    alternative = PricingRule(
        id="generic-alternative-rule", gateway="gateway_b", rule_name="Illustrative generic",
        currency="INR", fee_rate_pct=1.5, is_illustrative=True, version="1",
    )
    db.add_all([current, alternative])
    db.commit()

    missing_context = create_savings_scenario(SavingsScenarioCreate(
        name="Missing geography and method", current_gateway="gateway_a",
        alternative_gateway="gateway_b", currency="INR", eligible_volume=1000,
        current_pricing_rule_id=current.id, alternative_pricing_rule_id=alternative.id,
    ), db=db)
    assert missing_context["current_estimated_fee"] is None
    assert missing_context["alternative_estimated_fee"] is not None
    assert any("country" in item.lower() for item in missing_context["limitations"])
    assert any("payment method" in item.lower() for item in missing_context["limitations"])

    specified_context = create_savings_scenario(SavingsScenarioCreate(
        name="Specified geography and method", current_gateway="gateway_a",
        alternative_gateway="gateway_b", currency="INR", country="IN",
        payment_method="card", eligible_volume=1000,
        current_pricing_rule_id=current.id, alternative_pricing_rule_id=alternative.id,
    ), db=db)
    assert specified_context["current_estimated_fee"] is not None


def test_vendor_seed_and_checks_preserve_evidence_gaps(db):
    counts = seed_vendor_compliance_data(db)
    assert counts["vendors"] > 0
    vendors = db.query(VendorMaster).all()
    assert vendors
    for vendor in vendors:
        run_vendor_compliance_checks(db, vendor.id)
    db.commit()
    assert db.query(VendorScorecard).count() == len(vendors)
    assert db.query(VendorComplianceException).filter(
        VendorComplianceException.missing_information.is_not(None)
    ).count() > 0
