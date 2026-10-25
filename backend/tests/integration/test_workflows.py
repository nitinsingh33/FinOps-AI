"""End-to-end service checks on an isolated SQLite database."""
from __future__ import annotations

from decimal import Decimal
from datetime import timedelta
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
from app.services.analytics_service import get_gateway_cost_analysis, get_settlement_analysis
from app.services.vendor_compliance.synthetic_data import seed_vendor_compliance_data
from app.services.vendor_compliance.compliance_engine import run_vendor_compliance_checks
from app.api.v1.routers.reports import download_payments_csv, executive_summary
from app.api.v1.routers.pricing import (
    PricingRuleCreate, SavingsScenarioCreate, create_pricing_rule,
    create_savings_scenario, delete_pricing_rule, get_savings_scenario,
    list_pricing_rules, list_savings_scenarios, update_pricing_rule,
)

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
    assert all("observed_tax" in row and "fee_records_missing_amount" in row for row in monthly)
    assert all(
        row["observed_cost"] is None or row["fee_currency"] == row["tax_currency"]
        for row in monthly
    )
    settlement_data = get_settlement_analysis(db)
    settlement_metrics = settlement_data["monthly_settlement_metrics"]
    assert settlement_metrics
    assert {row["gateway"] for row in settlement_metrics} == {"gateway_a", "gateway_b"}
    assert all(row["timed_rows"] <= row["source_rows"] for row in settlement_metrics)
    assert all(row["median_hours"] is None or row["median_hours"] >= 0 for row in settlement_metrics)
    assert any(row["timing_basis"] == "balance available_on" for row in settlement_metrics)
    assert any(row["timing_basis"] == "payout effective timestamp" for row in settlement_metrics)
    assert "not independently verified bank receipt" in settlement_data["timing_data_note"]

    # Missing amounts stay visibly missing, and invalid negative settlement
    # durations do not enter monthly latency averages.
    captured = db.query(Payment).filter_by(gateway="gateway_a", status="captured").first()
    captured.fee = None
    captured.tax = None
    captured.tax_currency = None
    db.flush()
    affected = next(row for row in get_gateway_cost_analysis(db)["monthly_breakdowns"]
                    if row["gateway"] == "gateway_a" and row["currency"] == captured.currency
                    and row["tax_currency"] == "UNKNOWN"
                    and row["month"] == captured.transacted_at.strftime("%Y-%m"))
    assert affected["fee_records_missing_amount"] >= 1
    assert affected["tax_records_missing_amount"] >= 1
    assert affected["observed_cost"] is None
    assert affected["observed_cost_unavailable_reason"] == "currency_mismatch"

    gwa_payment_txns = db.query(GatewayTransaction).filter(
        GatewayTransaction.gateway == "gateway_a",
        GatewayTransaction.txn_type == "payment",
        GatewayTransaction.transacted_at.is_not(None),
    ).order_by(GatewayTransaction.id).limit(3).all()
    assert len(gwa_payment_txns) == 3
    missing_time_txn, negative_time_txn, conflicting_time_txn = gwa_payment_txns
    missing_time_txn.settled_at = None
    negative_time_txn.settled_at = negative_time_txn.transacted_at - timedelta(minutes=1)
    negative_time_txn.is_settled = True
    conflicting_time_txn.settled_at = conflicting_time_txn.transacted_at + timedelta(hours=1)
    conflicting_time_txn.is_settled = False
    db.flush()
    updated_metrics = get_settlement_analysis(db)["monthly_settlement_metrics"]
    missing_group = next(row for row in updated_metrics
                         if row["gateway"] == "gateway_a" and row["currency"] == missing_time_txn.currency
                         and row["month"] == missing_time_txn.transacted_at.strftime("%Y-%m")
                         and row["timing_basis"] == "transaction settled_at")
    assert missing_group["missing_completion_time"] >= 1
    negative_group = next(row for row in updated_metrics
                          if row["gateway"] == "gateway_a" and row["currency"] == negative_time_txn.currency
                          and row["month"] == negative_time_txn.transacted_at.strftime("%Y-%m")
                          and row["timing_basis"] == "transaction settled_at")
    assert negative_group["invalid_negative_duration"] >= 1
    conflict_group = next(row for row in updated_metrics
                          if row["gateway"] == "gateway_a" and row["currency"] == conflicting_time_txn.currency
                          and row["month"] == conflicting_time_txn.transacted_at.strftime("%Y-%m")
                          and row["timing_basis"] == "transaction settled_at")
    assert conflict_group["completion_time_unsettled_conflict"] >= 1

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
    assert "Payment Gateway Executive Summary" in page
    assert "Reporting period:" in page
    assert "Payment records" in page and "Gateway ledger records" in page
    assert "Gateway comparison" in page
    assert "Observed fees" in page
    assert "Effective rate" in page
    assert "Median settlement" in page
    assert "Gateway A" in page and "Gateway B" in page
    assert "Key findings" in page
    assert "Recommended next steps" in page
    assert page.count('class="finding"') == 3
    assert page.count('<li>') == 3
    comparison_rows = page.split('<tbody>', 1)[1].split('</tbody>', 1)[0].count('<tr>')
    assert 1 <= comparison_rows <= 5
    assert "not confirmed losses" in page
    assert "not independent bank evidence" in page
    assert "/analytics" in page and "/reconciliation" in page
    assert "Savings and routing" not in page
    assert "Priority issue" not in page
    assert "Amount at stake by currency" not in page


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
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        create_savings_scenario(SavingsScenarioCreate(
        name="Currency validation", current_gateway="gateway_a", alternative_gateway="gateway_b",
        currency="INR", eligible_volume=1000, current_pricing_rule_id=current.id,
        alternative_pricing_rule_id=alternative.id,
        ), db=db)
    assert exc.value.status_code == 422
    assert "currency" in str(exc.value.detail).lower()


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

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as missing_context:
        create_savings_scenario(SavingsScenarioCreate(
        name="Missing geography and method", current_gateway="gateway_a",
        alternative_gateway="gateway_b", currency="INR", eligible_volume=1000,
        current_pricing_rule_id=current.id, alternative_pricing_rule_id=alternative.id,
        ), db=db)
    assert missing_context.value.status_code == 422
    assert "country" in str(missing_context.value.detail).lower()

    specified_context = create_savings_scenario(SavingsScenarioCreate(
        name="Specified geography and method", current_gateway="gateway_a",
        alternative_gateway="gateway_b", currency="INR", country="IN",
        payment_method="card", eligible_volume=1000,
        current_pricing_rule_id=current.id, alternative_pricing_rule_id=alternative.id,
    ), db=db)
    assert specified_context["current_estimated_fee"] is not None
    assert specified_context["alternative_estimated_fee"] is not None
    assert specified_context["estimated_lower_cost_gateway"] == "gateway_b"
    assert specified_context["recommendation_status"] == "estimate_only_unverified_rates"
    assert specified_context["reliable_recommendation"] is False
    assert any("no geography scope" in item for item in specified_context["limitations"])
    assert any("no payment-method scope" in item for item in specified_context["limitations"])
    assert specified_context["fixed_fee_basis"] == "once_per_scenario"


def test_illustrative_pricing_rules_persist_and_scenario_matches_manual_calculation(db):
    # Explicitly hypothetical values for deterministic calculation verification.
    current = create_pricing_rule(PricingRuleCreate(
        rule_name="ILLUSTRATIVE Gateway A test rate", gateway="gateway_a",
        currency="inr", country="in", payment_method="card", fee_rate_pct=2,
        fixed_fee=5, fixed_fee_currency="INR", tax_on_fee_pct=18,
        is_illustrative=True,
    ), db=db)
    alternative = create_pricing_rule(PricingRuleCreate(
        rule_name="ILLUSTRATIVE Gateway B test rate", gateway="gateway_b",
        currency="INR", country="IN", payment_method="card", fee_rate_pct=1.5,
        fixed_fee=10, fixed_fee_currency="INR", tax_on_fee_pct=18,
        is_illustrative=True,
    ), db=db)
    overlapping = create_pricing_rule(PricingRuleCreate(
        rule_name="ILLUSTRATIVE Gateway A overlapping test rate", gateway="gateway_a",
        currency="INR", country="IN", payment_method="card", fee_rate_pct=2.1,
        is_illustrative=True,
    ), db=db)

    saved_rules = list_pricing_rules(db=db)
    assert {rule["id"] for rule in saved_rules} >= {current["id"], alternative["id"], overlapping["id"]}
    assert current["currency"] == "INR" and current["country"] == "IN"
    assert current["fixed_fee_currency"] == "INR"
    assert current["is_illustrative"] is True

    # A's (10,000 * 2% + 5) * 1.18 = 241.90.
    # B's (10,000 * 1.5% + 10) * 1.18 = 188.80.
    # Difference = 53.10, or 21.95% of A's estimate.
    result = create_savings_scenario(SavingsScenarioCreate(
        name="ILLUSTRATIVE deterministic comparison", current_gateway="gateway_a",
        alternative_gateway="gateway_b", currency="INR", country="IN",
        payment_method="card", eligible_volume=10_000,
        current_pricing_rule_id=current["id"], alternative_pricing_rule_id=alternative["id"],
    ), db=db)
    assert result["current_estimated_fee"] == "241.90"
    assert result["alternative_estimated_fee"] == "188.80"
    assert result["estimated_difference"] == "53.10"
    assert result["estimated_difference_pct"] == "21.95"
    assert result["estimated_lower_cost_gateway"] == "gateway_b"
    assert result["reliable_recommendation"] is False
    assert result["recommendation_status"] == "estimate_only_unverified_rates"
    assert any("illustrative" in note.lower() for note in result["limitations"])

    refreshed = get_savings_scenario(result["scenario_id"], db=db)
    assert refreshed["current_estimated_fee"] == "241.900000"
    assert refreshed["estimated_difference"] == "53.100000"
    assert refreshed["estimated_difference_pct"] == "21.95"
    history = list_savings_scenarios(db=db)
    assert any(item["scenario_id"] == result["scenario_id"] for item in history)
    saved = next(item for item in history if item["scenario_id"] == result["scenario_id"])
    assert saved["estimated_difference"] == "53.100000"
    assert saved["fixed_fee_basis"] == "once_per_scenario"


def test_pricing_rule_validation_rejects_invalid_assumptions():
    from pydantic import ValidationError

    valid = dict(rule_name="ILLUSTRATIVE", gateway="gateway_a", currency="INR")
    for invalid in (
        {"rule_name": "   "}, {"fee_rate_pct": -0.1}, {"fee_rate_pct": 100.1},
        {"fixed_fee": -1}, {"tax_on_fee_pct": 101}, {"min_fee": 20, "max_fee": 10},
        {"effective_from": "2027-01-01T00:00:00Z", "effective_to": "2026-01-01T00:00:00Z"},
        {"currency": "US$"}, {"currency": "USDT"}, {"fixed_fee_currency": "12"},
        {"country": "USA"},
    ):
        with pytest.raises(ValidationError):
            PricingRuleCreate(**(valid | invalid))
    with pytest.raises(ValidationError):
        PricingRuleCreate(gateway="gateway_a")


def test_scenario_missing_rules_zero_volume_and_invalid_rule_ids_are_safe(db):
    from fastapi import HTTPException
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SavingsScenarioCreate(name="bad", current_gateway="gateway_a", alternative_gateway="gateway_b",
                              currency="INR", eligible_volume=-1)
    with pytest.raises(ValidationError):
        SavingsScenarioCreate(name="bad", current_gateway="gateway_a", alternative_gateway="gateway_b",
                              currency="INR", eligible_volume=float("nan"))
    with pytest.raises(ValidationError):
        SavingsScenarioCreate(name="missing amount", current_gateway="gateway_a", alternative_gateway="gateway_b",
                              currency="INR", current_pricing_rule_id="a", alternative_pricing_rule_id="b")
    with pytest.raises(ValidationError):
        SavingsScenarioCreate(name="same gateway", current_gateway="gateway_a", alternative_gateway="gateway_a",
                              currency="INR", eligible_volume=100,
                              current_pricing_rule_id="a", alternative_pricing_rule_id="b")
    with pytest.raises(ValidationError):
        SavingsScenarioCreate(name="same rule", current_gateway="gateway_a", alternative_gateway="gateway_b",
                              currency="INR", eligible_volume=100,
                              current_pricing_rule_id="a", alternative_pricing_rule_id="a")
    with pytest.raises(ValidationError):
        SavingsScenarioCreate(name="rules required", current_gateway="gateway_a", alternative_gateway="gateway_b",
                              currency="INR", eligible_volume=100)

    zero_rule = create_pricing_rule(PricingRuleCreate(
        rule_name="ILLUSTRATIVE zero fee", gateway="gateway_a", currency="INR",
        country="IN", payment_method="card", fee_rate_pct=0, fixed_fee=0,
        fixed_fee_currency="INR", is_illustrative=True,
    ), db=db)
    zero_alternative = create_pricing_rule(PricingRuleCreate(
        rule_name="ILLUSTRATIVE zero Gateway B fee", gateway="gateway_b", currency="INR",
        country="IN", payment_method="card", fee_rate_pct=0, fixed_fee=0,
        fixed_fee_currency="INR", is_illustrative=True,
    ), db=db)
    zero_result = create_savings_scenario(SavingsScenarioCreate(
        name="Zero-volume scenario", current_gateway="gateway_a", alternative_gateway="gateway_b",
        currency="INR", country="IN", payment_method="card", eligible_volume=0,
        current_pricing_rule_id=zero_rule["id"], alternative_pricing_rule_id=zero_alternative["id"],
    ), db=db)
    assert zero_result["eligible_volume"] == "0.0"
    assert zero_result["current_estimated_fee"] == "0.00"
    stored_zero = get_savings_scenario(zero_result["scenario_id"], db=db)
    assert stored_zero["eligible_volume"] == "0.000000"
    assert stored_zero["current_estimated_fee"] == "0.000000"

    with pytest.raises(HTTPException) as exc:
        create_savings_scenario(SavingsScenarioCreate(
            name="Invalid rule reference", current_gateway="gateway_a", alternative_gateway="gateway_b",
            currency="INR", eligible_volume=1, current_pricing_rule_id="missing-rule",
            alternative_pricing_rule_id=zero_alternative["id"],
        ), db=db)
    assert exc.value.status_code == 404


def test_zero_max_fee_cap_is_applied(db):
    rule = PricingRule(id="zero-max", gateway="gateway_a", rule_name="Zero maximum",
                       currency="INR", fee_rate_pct=2, max_fee=0, version="1")
    db.add(rule)
    alternative = PricingRule(id="zero-max-alt", gateway="gateway_b", rule_name="Alternative rate",
                              currency="INR", fee_rate_pct=1, version="1")
    db.add(alternative)
    db.commit()
    result = create_savings_scenario(SavingsScenarioCreate(
        name="Zero max cap", current_gateway="gateway_a", alternative_gateway="gateway_b",
        currency="INR", eligible_volume=100, current_pricing_rule_id=rule.id,
        alternative_pricing_rule_id=alternative.id,
    ), db=db)
    assert result["current_estimated_fee"] == "0.00"


def test_pricing_rule_patch_is_persisted(db):
    created = create_pricing_rule(PricingRuleCreate(
        rule_name="ILLUSTRATIVE editable", gateway="gateway_a", currency="INR",
        country="IN", payment_method="card", fee_rate_pct=2, fixed_fee=5,
        fixed_fee_currency="INR", tax_on_fee_pct=18, min_fee=8, max_fee=50,
        is_international=True, effective_from="2026-01-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z", notes="source note", is_illustrative=True,
    ), db=db)
    preserved = update_pricing_rule(created["id"], PricingRuleCreate(
        rule_name="ILLUSTRATIVE edited", gateway="gateway_a", currency="INR",
        fee_rate_pct=1.75, is_illustrative=True,
    ), db=db)
    assert preserved["country"] == "IN"
    assert preserved["payment_method"] == "card"
    assert preserved["fixed_fee"] == "5.000000"
    assert preserved["min_fee"] == "8.000000"
    assert preserved["max_fee"] == "50.000000"
    assert preserved["is_international"] is True
    assert preserved["effective_from"] == created["effective_from"]
    assert preserved["effective_to"] == created["effective_to"]

    updated = update_pricing_rule(created["id"], PricingRuleCreate(
        rule_name="ILLUSTRATIVE edited", gateway="gateway_a", currency="INR",
        fee_rate_pct=1.75, is_illustrative=True, country=None, payment_method=None,
        fixed_fee=None, fixed_fee_currency=None, tax_on_fee_pct=None,
        min_fee=None, max_fee=None, is_international=None,
        effective_from=None, effective_to=None, notes=None,
    ), db=db)
    assert updated["rule_name"] == "ILLUSTRATIVE edited"
    assert Decimal(updated["fee_rate_pct"]) == Decimal("1.75")
    assert updated["country"] is None
    assert updated["payment_method"] is None
    assert updated["fixed_fee"] is None
    assert updated["fixed_fee_currency"] is None
    assert updated["tax_on_fee_pct"] is None
    assert updated["min_fee"] is None
    assert updated["max_fee"] is None
    assert updated["is_international"] is None
    assert updated["effective_from"] is None
    assert updated["effective_to"] is None
    assert updated["notes"] is None
    assert next(rule for rule in list_pricing_rules(db=db) if rule["id"] == created["id"])["rule_name"] == "ILLUSTRATIVE edited"


def test_pricing_rule_delete_only_removes_unreferenced_rules(db):
    from fastapi import HTTPException
    from app.main import app

    assert any(
        route.path == "/api/v1/pricing-rules/{rule_id}" and "DELETE" in route.methods
        for route in app.routes
    )

    unreferenced = create_pricing_rule(PricingRuleCreate(
        rule_name="ILLUSTRATIVE removable", gateway="gateway_a", currency="INR", fee_rate_pct=2,
    ), db=db)
    assert delete_pricing_rule(unreferenced["id"], db=db) == {"deleted": True, "id": unreferenced["id"]}
    assert all(rule["id"] != unreferenced["id"] for rule in list_pricing_rules(db=db))
    with pytest.raises(HTTPException) as missing:
        delete_pricing_rule(unreferenced["id"], db=db)
    assert missing.value.status_code == 404

    referenced = create_pricing_rule(PricingRuleCreate(
        rule_name="ILLUSTRATIVE protected", gateway="gateway_a", currency="INR", fee_rate_pct=2,
    ), db=db)
    referenced_alternative = create_pricing_rule(PricingRuleCreate(
        rule_name="ILLUSTRATIVE protected alternative", gateway="gateway_b", currency="INR", fee_rate_pct=1,
    ), db=db)
    create_savings_scenario(SavingsScenarioCreate(
        name="Scenario retains rule reference", current_gateway="gateway_a", alternative_gateway="gateway_b",
        currency="INR", eligible_volume=100, current_pricing_rule_id=referenced["id"],
        alternative_pricing_rule_id=referenced_alternative["id"],
    ), db=db)
    with pytest.raises(HTTPException) as conflict:
        delete_pricing_rule(referenced["id"], db=db)
    assert conflict.value.status_code == 409
    assert any(rule["id"] == referenced["id"] for rule in list_pricing_rules(db=db))


def test_missing_fee_rate_remains_explicit_and_cost_is_unavailable(db):
    rule = create_pricing_rule(PricingRuleCreate(
        rule_name="Legacy Gateway A rule without a rate", gateway="gateway_a", currency="INR",
    ), db=db)
    assert rule["fee_rate_pct"] is None
    alternative = create_pricing_rule(PricingRuleCreate(
        rule_name="ILLUSTRATIVE Gateway B with rate", gateway="gateway_b", currency="INR", fee_rate_pct=1,
    ), db=db)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        create_savings_scenario(SavingsScenarioCreate(
        name="Missing rate", current_gateway="gateway_a", alternative_gateway="gateway_b",
        currency="INR", eligible_volume=1000, current_pricing_rule_id=rule["id"],
        alternative_pricing_rule_id=alternative["id"],
        ), db=db)
    assert exc.value.status_code == 422
    assert "percentage fee rate" in str(exc.value.detail)


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
