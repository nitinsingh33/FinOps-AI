"""
Unit tests for financial arithmetic and core reconciliation logic.
"""
from __future__ import annotations
import pytest
from decimal import Decimal
from datetime import datetime, date, timezone, timedelta
from unittest.mock import MagicMock

from app.services.adapters.excel_adapters import (
    normalize_currency, safe_decimal, parse_dt_gwa, parse_dt_gwb,
)


class TestNormalizeCurrency:
    def test_known_currency(self):
        assert normalize_currency("inr") == "INR"
        assert normalize_currency("USD") == "USD"

    def test_none_returns_none(self):
        assert normalize_currency(None) is None

    def test_nan_float_returns_none(self):
        assert normalize_currency(float("nan")) is None

    def test_unknown_three_letter_accepted(self):
        assert normalize_currency("XYZ") == "XYZ"

    def test_non_three_letter_unknown_returns_none(self):
        assert normalize_currency("RUPEE") is None

    def test_empty_string_returns_none(self):
        assert normalize_currency("") is None


class TestSafeDecimal:
    def test_valid_integer(self):
        val, warn = safe_decimal(100)
        assert val == Decimal("100")
        assert warn is None

    def test_comma_formatted(self):
        val, warn = safe_decimal("1,234.56")
        assert val == Decimal("1234.56")

    def test_none_returns_none(self):
        val, warn = safe_decimal(None)
        assert val is None
        assert warn is None

    def test_nan_float_returns_none(self):
        val, warn = safe_decimal(float("nan"))
        assert val is None

    def test_invalid_string_returns_warning(self):
        val, warn = safe_decimal("not_a_number", "amount")
        assert val is None
        assert warn is not None
        assert "amount" in warn

    def test_zero_is_valid(self):
        val, warn = safe_decimal(0)
        assert val == Decimal("0")

    def test_dash_placeholder_is_none(self):
        val, warn = safe_decimal("-")
        assert val is None


class TestParseDateGWA:
    def test_slash_format(self):
        dt, warn = parse_dt_gwa("01/09/2026 14:30:00")
        assert dt is not None and dt.month == 9 and dt.day == 1
        assert warn is None

    def test_dash_format(self):
        dt, warn = parse_dt_gwa("15-09-2026")
        assert dt is not None and dt.day == 15

    def test_none_returns_none(self):
        dt, warn = parse_dt_gwa(None)
        assert dt is None

    def test_datetime_passthrough_gets_utc(self):
        original = datetime(2026, 9, 15, 10, 0, 0)
        dt, warn = parse_dt_gwa(original)
        assert dt.tzinfo is not None

    def test_invalid_date_produces_warning(self):
        dt, warn = parse_dt_gwa("not-a-date")
        assert dt is None and warn is not None


from app.api.v1.routers.pricing import _estimate_fee
from app.models.models import PricingRule


def _make_rule(fee_rate_pct, fixed_fee=None, tax_on_fee_pct=None,
               min_fee=None, max_fee=None):
    rule = MagicMock(spec=PricingRule)
    rule.fee_rate_pct = Decimal(str(fee_rate_pct))
    rule.fixed_fee = Decimal(str(fixed_fee)) if fixed_fee is not None else None
    rule.tax_on_fee_pct = Decimal(str(tax_on_fee_pct)) if tax_on_fee_pct is not None else None
    rule.min_fee = Decimal(str(min_fee)) if min_fee is not None else None
    rule.max_fee = Decimal(str(max_fee)) if max_fee is not None else None
    return rule


class TestEstimateFee:
    def test_percentage_only(self):
        rule = _make_rule(2.0)
        assert _estimate_fee(Decimal("10000.00"), rule) == Decimal("200.00")

    def test_percentage_plus_fixed(self):
        rule = _make_rule(1.5, fixed_fee=10.0)
        assert _estimate_fee(Decimal("1000.00"), rule) == Decimal("25.00")

    def test_min_fee_applied(self):
        rule = _make_rule(0.1, min_fee=50.0)
        assert _estimate_fee(Decimal("100.00"), rule) == Decimal("50.00")

    def test_max_fee_applied(self):
        rule = _make_rule(5.0, max_fee=100.0)
        assert _estimate_fee(Decimal("100000.00"), rule) == Decimal("100.00")

    def test_tax_on_fee(self):
        rule = _make_rule(2.0, tax_on_fee_pct=18.0)
        assert _estimate_fee(Decimal("1000.00"), rule) == Decimal("23.60")

    def test_none_rule_returns_none(self):
        assert _estimate_fee(Decimal("5000.00"), None) is None


class TestReconciliationInvariants:
    def test_refund_aggregation_same_currency(self):
        total = sum([Decimal("100.00"), Decimal("50.00"), Decimal("25.00")], Decimal("0"))
        assert total == Decimal("175.00")

    def test_refund_excludes_failed(self):
        items = [("processed", Decimal("100")), ("failed", Decimal("50")),
                 ("cancelled", Decimal("25")), ("processed", Decimal("200"))]
        total = sum(
            (a for s, a in items if s not in ("failed", "cancelled")),
            Decimal("0"),
        )
        assert total == Decimal("300")

    def test_missing_amount_is_none_not_zero(self):
        val, _ = safe_decimal(None)
        assert val is None

    def test_fee_discrepancy_exceeds_threshold(self):
        diff = abs(Decimal("105.50") - Decimal("104.00"))
        assert diff > Decimal("1.00")

    def test_fee_within_threshold(self):
        diff = abs(Decimal("105.50") - Decimal("105.20"))
        assert diff < Decimal("1.00")

    def test_net_formula(self):
        expected_net = Decimal("1000.00") - Decimal("20.00") - Decimal("3.60")
        assert expected_net == Decimal("976.40")

    def test_settlement_delay_flagged(self):
        diff = datetime(2026, 9, 10, tzinfo=timezone.utc) - datetime(2026, 9, 1, tzinfo=timezone.utc)
        assert diff.days > 7

    def test_settlement_on_time(self):
        diff = datetime(2026, 9, 5, tzinfo=timezone.utc) - datetime(2026, 9, 1, tzinfo=timezone.utc)
        assert diff.days <= 7


class TestExcelAdapterRowCounts:
    def test_gwa_payments(self):
        from app.services.adapters.excel_adapters import parse_gwa_payments
        r = parse_gwa_payments("../data/GatewayA_payments_Sep26_dummy.xlsx")
        assert r.total_rows == 475 and r.rejected_rows == 0

    def test_gwa_transactions(self):
        from app.services.adapters.excel_adapters import parse_gwa_transactions
        r = parse_gwa_transactions("../data/GatewayA_transactions_Sep26_dummy.xlsx")
        assert r.total_rows == 414 and r.rejected_rows == 0

    def test_gwa_refunds(self):
        from app.services.adapters.excel_adapters import parse_gwa_refunds
        r = parse_gwa_refunds("../data/GatewayA_refunds_Sep26_dummy.xlsx")
        assert r.total_rows == 13 and r.rejected_rows == 0

    def test_gwb_balance(self):
        from app.services.adapters.excel_adapters import parse_gwb_balance
        r = parse_gwb_balance("../data/GatewayB_Sep26_dummy.xlsx")
        assert r.total_rows == 731 and r.rejected_rows == 0

    def test_gwa_payments_gateway_field(self):
        from app.services.adapters.excel_adapters import parse_gwa_payments
        r = parse_gwa_payments("../data/GatewayA_payments_Sep26_dummy.xlsx")
        for rec in r.records:
            assert rec["gateway"] == "gateway_a"

    def test_gwa_refunds_have_payment_link(self):
        from app.services.adapters.excel_adapters import parse_gwa_refunds
        r = parse_gwa_refunds("../data/GatewayA_refunds_Sep26_dummy.xlsx")
        for rec in r.records:
            assert rec.get("gateway_payment_id") is not None


class TestGSTINValidation:
    def test_valid_gstin(self):
        from app.services.vendor_compliance.gst_checks import validate_gstin_format
        valid, msg = validate_gstin_format("27AABCU9603R1ZX")
        assert valid is True and msg is None

    def test_invalid_too_short(self):
        from app.services.vendor_compliance.gst_checks import validate_gstin_format
        valid, msg = validate_gstin_format("27AABCU9603")
        assert valid is False

    def test_none_gstin(self):
        from app.services.vendor_compliance.gst_checks import validate_gstin_format
        valid, _ = validate_gstin_format(None)
        assert valid is False

    def test_pan_extraction(self):
        from app.services.vendor_compliance.gst_checks import extract_pan_from_gstin
        pan = extract_pan_from_gstin("27AABCU9603R1ZX")
        assert pan == "AABCU9603R"

    def test_reverse_charge_supplier_tax_is_flagged(self):
        from app.services.vendor_compliance.gst_checks import validate_invoice_gst_treatment
        valid, message = validate_invoice_gst_treatment(
            "intra_state", Decimal("900"), Decimal("900"), Decimal("0"), is_rcm=True
        )
        assert valid is False and "Reverse-charge" in message

    def test_reverse_charge_without_supplier_tax_is_not_flagged(self):
        from app.services.vendor_compliance.gst_checks import validate_invoice_gst_treatment
        valid, message = validate_invoice_gst_treatment(
            "intra_state", Decimal("0"), Decimal("0"), Decimal("0"), is_rcm=True
        )
        assert valid is True and message is None


class TestPANValidation:
    def test_valid_pan(self):
        from app.services.vendor_compliance.gst_checks import validate_pan_format
        valid, _ = validate_pan_format("AABCU9603R")
        assert valid is True

    def test_lowercase_is_normalized(self):
        from app.services.vendor_compliance.gst_checks import validate_pan_format
        valid, error = validate_pan_format("aabcu9603r")
        assert valid is True and error is None


class TestTDSCalculation:
    def test_tds_excludes_gst(self):
        tds_base = Decimal("11800.00") - Decimal("1800.00")
        tds = tds_base * Decimal("1.00") / 100
        assert tds_base == Decimal("10000.00") and tds == Decimal("100.00")

    def test_three_way_tds_flags_deposit_and_return_mismatches(self):
        from app.services.vendor_compliance.tds_checks import three_way_tds_reconciliation
        result = three_way_tds_reconciliation(Decimal("100"), Decimal("80"), Decimal("75"))
        assert {issue["type"] for issue in result["issues"]} == {"deposit_mismatch", "reporting_mismatch"}


class TestITCPaymentDeadline:
    def test_partial_payment_after_180_days_keeps_unpaid_balance_at_risk(self):
        from app.services.vendor_compliance.gst_checks import check_itc_180_day_rule
        status, message = check_itc_180_day_rule(
            date(2026, 1, 1), None, Decimal("500"), Decimal("1000"), date(2026, 7, 10)
        )
        assert status == "reversal_required" and "unpaid consideration" in message.lower()

    def test_partial_payment_before_180_days_is_pending(self):
        from app.services.vendor_compliance.gst_checks import check_itc_180_day_rule
        status, message = check_itc_180_day_rule(
            date(2026, 1, 1), None, Decimal("500"), Decimal("1000"), date(2026, 2, 1)
        )
        assert status == "pending" and "partially paid" in message


class TestMSMEPaymentDeadline:
    def test_within_45_days(self):
        days = (date(2026, 10, 10) - date(2026, 9, 1)).days
        assert days <= 45

    def test_beyond_45_days(self):
        days = (date(2026, 10, 20) - date(2026, 9, 1)).days
        assert days > 45

    def test_exactly_45(self):
        days = (date(2026, 10, 16) - date(2026, 9, 1)).days
        assert days == 45

    def test_partial_payment_does_not_close_deadline(self):
        from app.services.vendor_compliance.msme_checks import check_msme_payment_deadline
        result = check_msme_payment_deadline(
            invoice_date=date(2026, 1, 1), acceptance_date=None, payment_date=None,
            msme_type="small", udyam_number="UDYAM-KA-07-0001234", is_msme_verified=True,
            paid_amount=Decimal("500"), invoice_amount=Decimal("1000"), as_of_date=date(2026, 3, 1),
        )
        assert result["status"] == "breach" and result["is_flagged"]


class TestSavingsScenario:
    def test_difference_is_deterministic(self):
        diff = Decimal("500.00") - Decimal("350.00")
        assert diff == Decimal("150.00")

    def test_alt_more_expensive_is_negative(self):
        diff = Decimal("300.00") - Decimal("400.00")
        assert diff < Decimal("0")
