"""
Analytics service — real calculations from the database.
No hardcoded values. All metrics are aggregated from imported records.
Currencies are never mixed in totals.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from statistics import median
from typing import Any, Dict, List, Optional

from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app.models.models import (
    GatewayTransaction,
    ImportJob,
    ImportStatus,
    Payment,
    ReconciliationException,
    ReconciliationRun,
    ReconciliationStatus,
    Refund,
    ReviewStatus,
    UploadedDataset,
)


def get_overview_stats(db: Session) -> Dict[str, Any]:
    """
    Compute overview dashboard metrics from actual database records.
    Returns separate totals per currency — never mixed.
    """
    result: Dict[str, Any] = {}

    # --- Payment volume by gateway and currency ---
    gwa_vol = (
        db.query(
            Payment.currency,
            func.sum(Payment.gross_amount).label("total_gross"),
            func.count(Payment.id).label("count"),
        )
        .filter(Payment.status == "captured")
        .group_by(Payment.currency)
        .all()
    )
    result["gateway_a_volume"] = [
        {"currency": r.currency, "total_gross": float(r.total_gross or 0), "count": r.count}
        for r in gwa_vol
    ]

    gwb_vol = (
        db.query(
            GatewayTransaction.currency,
            func.sum(GatewayTransaction.gross_amount).label("total_gross"),
            func.count(GatewayTransaction.id).label("count"),
        )
        .filter(
            GatewayTransaction.gateway == "gateway_b",
            GatewayTransaction.txn_type == "charge",
        )
        .group_by(GatewayTransaction.currency)
        .all()
    )
    result["gateway_b_volume"] = [
        {"currency": r.currency, "total_gross": float(r.total_gross or 0), "count": r.count}
        for r in gwb_vol
    ]

    # --- Transaction status counts ---
    gwa_status = (
        db.query(Payment.status, func.count(Payment.id).label("count"))
        .filter(Payment.gateway == "gateway_a")
        .group_by(Payment.status)
        .all()
    )
    result["gwa_status_breakdown"] = {r.status: r.count for r in gwa_status}

    gwb_cat = (
        db.query(
            GatewayTransaction.reporting_category,
            func.count(GatewayTransaction.id).label("count"),
        )
        .filter(GatewayTransaction.gateway == "gateway_b")
        .group_by(GatewayTransaction.reporting_category)
        .all()
    )
    result["gwb_category_breakdown"] = {r.reporting_category: r.count for r in gwb_cat}

    # --- Fees by gateway and currency ---
    gwa_fee_rows = (
        db.query(Payment.fee_currency.label("currency"), func.sum(Payment.fee).label("total_fee"),
                 Payment.tax_currency.label("tax_currency"), func.sum(Payment.tax).label("total_tax"))
        .filter(Payment.gateway == "gateway_a")
        .group_by(Payment.fee_currency, Payment.tax_currency)
        .all()
    )
    result["gateway_a_fees"] = [
        {"currency": r.currency, "total_fee": float(r.total_fee or 0),
         "tax_currency": r.tax_currency, "total_tax": float(r.total_tax or 0)}
        for r in gwa_fee_rows
    ]

    gwb_fees = (
        db.query(
            GatewayTransaction.currency,
            func.sum(GatewayTransaction.fee).label("total_fee"),
        )
        .filter(
            GatewayTransaction.gateway == "gateway_b",
            GatewayTransaction.txn_type == "charge",
        )
        .group_by(GatewayTransaction.currency)
        .all()
    )
    result["gateway_b_fees"] = [
        {"currency": r.currency, "total_fee": float(r.total_fee or 0)}
        for r in gwb_fees
    ]

    # --- Effective fee rate (INR captured payments only — must use same currency) ---
    gwa_inr = (
        db.query(
            func.sum(Payment.gross_amount).label("gross"),
            func.sum(Payment.fee).label("fee"),
        )
        .filter(
            Payment.gateway == "gateway_a",
            Payment.currency == "INR",
            Payment.fee_currency == "INR",
            Payment.status == "captured",
            Payment.fee.isnot(None),
        )
        .first()
    )
    if gwa_inr and gwa_inr.gross and float(gwa_inr.gross) > 0:
        result["gwa_effective_fee_rate_inr"] = round(
            float(gwa_inr.fee) / float(gwa_inr.gross) * 100, 4
        )
    else:
        result["gwa_effective_fee_rate_inr"] = None

    gwb_inr = (
        db.query(
            func.sum(GatewayTransaction.gross_amount).label("gross"),
            func.sum(GatewayTransaction.fee).label("fee"),
        )
        .filter(
            GatewayTransaction.gateway == "gateway_b",
            GatewayTransaction.currency == "INR",
            GatewayTransaction.fee.isnot(None),
            GatewayTransaction.txn_type == "charge",
        )
        .first()
    )
    if gwb_inr and gwb_inr.gross and float(gwb_inr.gross) > 0:
        result["gwb_effective_fee_rate_inr"] = round(
            float(gwb_inr.fee) / float(gwb_inr.gross) * 100, 4
        )
    else:
        result["gwb_effective_fee_rate_inr"] = None

    # --- Refund summary ---
    refund_summary = (
        db.query(
            Refund.currency,
            func.sum(Refund.amount).label("total"),
            func.count(Refund.id).label("count"),
        )
        .group_by(Refund.currency)
        .all()
    )
    result["refund_summary"] = [
        {"currency": r.currency, "total_refunded": float(r.total), "count": r.count}
        for r in refund_summary
    ]

    # --- Reconciliation stats ---
    latest_run = (
        db.query(ReconciliationRun)
        .filter(ReconciliationRun.status == ReconciliationStatus.COMPLETED)
        .order_by(ReconciliationRun.created_at.desc())
        .first()
    )
    if latest_run:
        result["latest_reconciliation"] = {
            "run_id": latest_run.id,
            "matched": latest_run.matched_records,
            "exceptions": latest_run.exception_count,
            "match_rate_pct": latest_run.summary.get("match_rate_pct") if latest_run.summary else None,
            "completed_at": latest_run.completed_at.isoformat() if latest_run.completed_at else None,
        }
    else:
        result["latest_reconciliation"] = None

    # --- Open exceptions ---
    open_exceptions = (
        db.query(ReconciliationException.category, func.count(ReconciliationException.id).label("count"))
        .filter(ReconciliationException.review_status == ReviewStatus.OPEN)
        .group_by(ReconciliationException.category)
        .all()
    )
    result["open_exceptions_by_category"] = {r.category: r.count for r in open_exceptions}
    result["total_open_exceptions"] = sum(r.count for r in open_exceptions)
    result["open_exceptions"] = result["total_open_exceptions"]

    # KPI values are counts from persisted rows, never guessed from summaries.
    result["total_payments"] = db.query(func.count(Payment.id)).scalar() or 0
    result["total_transactions"] = db.query(func.count(GatewayTransaction.id)).scalar() or 0
    result["total_refunds"] = db.query(func.count(Refund.id)).scalar() or 0
    result["total_exceptions"] = db.query(func.count(ReconciliationException.id)).scalar() or 0
    result["reconciliation_runs"] = db.query(func.count(ReconciliationRun.id)).scalar() or 0
    result["matched_records"] = latest_run.matched_records if latest_run else 0
    result["unmatched_records"] = latest_run.unmatched_records if latest_run else 0

    # --- Import activity ---
    recent_jobs = (
        db.query(ImportJob)
        .order_by(ImportJob.created_at.desc())
        .limit(5)
        .all()
    )
    result["recent_imports"] = [
        {
            "job_id": j.id,
            "dataset_id": j.dataset_id,
            "status": j.status,
            "imported_rows": j.imported_rows,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        }
        for j in recent_jobs
    ]

    return result


def get_gateway_cost_analysis(db: Session, gateway: Optional[str] = None) -> Dict[str, Any]:
    """
    Compute gateway cost metrics per currency and payment method.
    Never mixes currencies.
    """
    result: Dict[str, Any] = {}

    for gw, model_filter in [
        ("gateway_a", Payment.gateway == "gateway_a"),
        ("gateway_b", GatewayTransaction.gateway == "gateway_b"),
    ]:
        if gateway and gw != gateway:
            continue

        if gw == "gateway_a":
            rows = (
                db.query(
                    Payment.currency,
                    Payment.fee_currency,
                    Payment.tax_currency,
                    Payment.payment_method,
                    Payment.card_network,
                    func.count(Payment.id).label("count"),
                    func.sum(Payment.gross_amount).label("gross"),
                    func.sum(Payment.fee).label("fees"),
                    func.sum(Payment.tax).label("taxes"),
                )
                .filter(Payment.status == "captured", Payment.fee.isnot(None))
                .group_by(Payment.currency, Payment.fee_currency, Payment.tax_currency, Payment.payment_method, Payment.card_network)
                .all()
            )
            result["gateway_a"] = [
                {
                    "currency": r.currency,
                    "fee_currency": r.fee_currency,
                    "tax_currency": r.tax_currency,
                    "payment_method": r.payment_method,
                    "card_network": r.card_network,
                    "transaction_count": r.count,
                    "gross_volume": float(r.gross or 0),
                    "total_fees": float(r.fees or 0),
                    "total_taxes": float(r.taxes or 0),
                    "effective_fee_rate_pct": round(
                        float(r.fees) / float(r.gross) * 100, 4
                    ) if r.currency == r.fee_currency and r.gross and float(r.gross) > 0 and r.fees else None,
                }
                for r in rows
            ]
        else:
            rows = (
                db.query(
                    GatewayTransaction.currency,
                    GatewayTransaction.card_brand,
                    GatewayTransaction.card_funding,
                    GatewayTransaction.country,
                    func.count(GatewayTransaction.id).label("count"),
                    func.sum(GatewayTransaction.gross_amount).label("gross"),
                    func.sum(GatewayTransaction.fee).label("fees"),
                    func.sum(GatewayTransaction.net_amount).label("net"),
                )
                .filter(
                    GatewayTransaction.gateway == "gateway_b",
                    GatewayTransaction.txn_type == "charge",
                )
                .group_by(
                    GatewayTransaction.currency,
                    GatewayTransaction.card_brand,
                    GatewayTransaction.card_funding,
                    GatewayTransaction.country,
                )
                .all()
            )
            result["gateway_b"] = [
                {
                    "currency": r.currency,
                    "fee_currency": r.currency,
                    "tax_currency": r.currency,
                    "card_brand": r.card_brand,
                    "card_funding": r.card_funding,
                    "country": r.country,
                    "transaction_count": r.count,
                    "gross_volume": float(r.gross or 0),
                    "total_fees": float(r.fees or 0),
                    "total_net": float(r.net or 0),
                    "effective_fee_rate_pct": round(
                        float(r.fees) / float(r.gross) * 100, 4
                    ) if r.gross and float(r.gross) > 0 and r.fees else None,
                }
                for r in rows
            ]

    result["breakdowns"] = [
        {"gateway": "gateway_a", "currency": r["currency"], "fee_currency": r["fee_currency"],
         "tax_currency": r["tax_currency"], "payment_method": r["payment_method"],
         "payment_count": r["transaction_count"], "gross_volume": r["gross_volume"],
         "total_fees": r["total_fees"], "total_tax": r["total_taxes"],
         "effective_rate_pct": r["effective_fee_rate_pct"]}
        for r in result.get("gateway_a", [])
    ] + [
        {"gateway": "gateway_b", "currency": r["currency"], "fee_currency": r["fee_currency"],
         "tax_currency": r["tax_currency"], "payment_method": None,
         "payment_count": r["transaction_count"], "gross_volume": r["gross_volume"],
         "total_fees": r["total_fees"], "total_tax": 0,
         "effective_rate_pct": r["effective_fee_rate_pct"]}
        for r in result.get("gateway_b", [])
    ]
    result["summary"] = {
        "gateway_a_records": sum(r["transaction_count"] for r in result.get("gateway_a", [])),
        "gateway_b_records": sum(r["transaction_count"] for r in result.get("gateway_b", [])),
        "currency_groups": len(result["breakdowns"]),
    }

    # Month-wise observed costs, grouped by gateway and currency so unlike
    # currencies are never added together. Use transaction timestamps from
    # imported records, not upload/ingestion timestamps.
    monthly: Dict[tuple, Dict[str, Any]] = {}
    undated_rows = 0

    def add_monthly(gateway_name: str, timestamp: Any, currency: str,
                    fee_currency: Optional[str], tax_currency: Optional[str],
                    gross: Any, fee: Any, tax: Any) -> None:
        nonlocal undated_rows
        if timestamp is None:
            undated_rows += 1
            return
        month = timestamp.strftime("%Y-%m")
        source_fee_currency = fee_currency or currency
        source_tax_currency = tax_currency or "UNKNOWN"
        key = (month, gateway_name, currency, source_fee_currency, source_tax_currency)
        row = monthly.setdefault(key, {
            "month": month,
            "gateway": gateway_name,
            "currency": currency,
            "fee_currency": source_fee_currency,
            "tax_currency": source_tax_currency,
            "transaction_count": 0,
            "gross_volume": Decimal("0"),
            "observed_fees": Decimal("0"),
            "observed_tax": Decimal("0"),
            "fee_records_with_amount": 0,
            "fee_records_missing_amount": 0,
            "tax_records_with_amount": 0,
            "tax_records_missing_amount": 0,
        })
        row["transaction_count"] += 1
        row["gross_volume"] += gross or Decimal("0")
        if fee is None:
            row["fee_records_missing_amount"] += 1
        else:
            row["fee_records_with_amount"] += 1
            row["observed_fees"] += fee
        if tax is None:
            row["tax_records_missing_amount"] += 1
        else:
            row["tax_records_with_amount"] += 1
            row["observed_tax"] += tax

    payment_rows = []
    if not gateway or gateway == "gateway_a":
        payment_rows = db.query(
            Payment.transacted_at, Payment.currency, Payment.fee_currency,
            Payment.tax_currency, Payment.gross_amount, Payment.fee, Payment.tax,
        ).filter(Payment.gateway == "gateway_a", Payment.status == "captured").all()
    for row in payment_rows:
        add_monthly("gateway_a", row.transacted_at, row.currency,
                    row.fee_currency, row.tax_currency, row.gross_amount, row.fee, row.tax)

    gateway_b_rows = []
    if not gateway or gateway == "gateway_b":
        gateway_b_rows = db.query(
            GatewayTransaction.transacted_at, GatewayTransaction.currency,
            GatewayTransaction.gross_amount, GatewayTransaction.fee, GatewayTransaction.tax,
        ).filter(
            GatewayTransaction.gateway == "gateway_b",
            GatewayTransaction.txn_type == "charge",
        ).all()
    for row in gateway_b_rows:
        add_monthly("gateway_b", row.transacted_at, row.currency,
                    row.currency, row.currency, row.gross_amount, row.fee, row.tax)

    monthly_rows = []
    for key in sorted(monthly):
        row = monthly[key]
        gross = row["gross_volume"]
        fees = row["observed_fees"]
        monthly_rows.append({
            **row,
            "gross_volume": float(gross),
            "observed_fees": float(fees),
            "observed_tax": float(row["observed_tax"]),
            "fee_records_with_amount": row["fee_records_with_amount"],
            "fee_records_missing_amount": row["fee_records_missing_amount"],
            "tax_records_with_amount": row["tax_records_with_amount"],
            "tax_records_missing_amount": row["tax_records_missing_amount"],
            "observed_cost": float(fees + row["observed_tax"])
                if row["fee_currency"] == row["tax_currency"]
                and row["fee_records_missing_amount"] == 0
                and row["tax_records_missing_amount"] == 0 else None,
            "observed_cost_currency": row["fee_currency"]
                if row["fee_currency"] == row["tax_currency"]
                and row["fee_records_missing_amount"] == 0
                and row["tax_records_missing_amount"] == 0 else None,
            "observed_cost_unavailable_reason": (
                "currency_mismatch" if row["fee_currency"] != row["tax_currency"]
                else "missing_amounts" if row["fee_records_missing_amount"] or row["tax_records_missing_amount"]
                else None
            ),
            "effective_fee_rate_pct": round(float(fees / gross * 100), 4)
                if gross and row["currency"] == row["fee_currency"] and row["fee_records_missing_amount"] == 0 else None,
        })
    result["monthly_breakdowns"] = monthly_rows
    result["monthly_data_note"] = (
        f"Based on captured Gateway A payments and Gateway B charge rows; "
        f"{undated_rows} eligible rows without transaction dates are omitted. "
        "Fees and taxes are reported separately in their source currencies; observed cost is shown only when fee and tax currencies match. Missing amounts are not treated as zero. Fees are not verified contract rates."
    )
    return result


def get_settlement_analysis(db: Session) -> Dict[str, Any]:
    """Summarize source-recorded settlement/availability timings by transaction month.

    Gateway A uses its transaction ledger settled_at. Gateway B reports both the
    balance-export available_on delay and its payout-effective timestamp. These
    source fields do not constitute independent bank confirmation.
    """
    rows = db.query(GatewayTransaction).filter(
        GatewayTransaction.txn_type == "payment",
        GatewayTransaction.gateway == "gateway_a",
    ).all()
    b_rows = db.query(GatewayTransaction).filter(
        GatewayTransaction.txn_type == "charge",
        GatewayTransaction.gateway == "gateway_b",
    ).all()
    groups: Dict[tuple, Dict[str, Any]] = {}

    def add(gateway: str, currency: str, basis: str, transaction_at: Any,
            completion_at: Any, settled_flag: Optional[bool]) -> None:
        if transaction_at is None:
            return
        month = transaction_at.strftime("%Y-%m")
        key = (month, gateway, currency, basis)
        group = groups.setdefault(key, {
            "month": month, "gateway": gateway, "currency": currency,
            "timing_basis": basis, "source_rows": 0, "settled_or_payout_linked": 0,
            "explicitly_unsettled": 0, "settlement_status_unknown": 0,
            "missing_completion_time": 0, "invalid_negative_duration": 0,
            "completion_time_unsettled_conflict": 0,
            "durations_hours": [],
        })
        group["source_rows"] += 1
        if settled_flag is True:
            group["settled_or_payout_linked"] += 1
        elif settled_flag is False:
            group["explicitly_unsettled"] += 1
        else:
            group["settlement_status_unknown"] += 1
        if completion_at is None:
            group["missing_completion_time"] += 1
            return
        if settled_flag is False:
            group["completion_time_unsettled_conflict"] += 1
            return
        delta = completion_at - transaction_at
        hours = delta.total_seconds() / 3600
        if hours < 0:
            group["invalid_negative_duration"] += 1
            return
        group["durations_hours"].append(hours)

    for txn in rows:
        add("gateway_a", txn.currency, "transaction settled_at", txn.transacted_at,
            txn.settled_at, txn.is_settled)
    for txn in b_rows:
        add("gateway_b", txn.currency, "balance available_on", txn.transacted_at,
            txn.available_on, txn.is_settled)
        if txn.payout_id:
            add("gateway_b", txn.currency, "payout effective timestamp", txn.transacted_at,
                txn.settled_at, txn.is_settled)

    monthly = []
    for key in sorted(groups):
        group = groups[key]
        durations = group.pop("durations_hours")
        group["timed_rows"] = len(durations)
        group["average_hours"] = round(sum(durations) / len(durations), 2) if durations else None
        group["median_hours"] = round(median(durations), 2) if durations else None
        monthly.append(group)

    # Preserve the existing settlement and payout summaries for current UI/API users.
    from sqlalchemy import case
    gwa_settled = (
        db.query(GatewayTransaction.txn_type, GatewayTransaction.currency,
                 func.count(GatewayTransaction.id).label("count"),
                 func.sum(GatewayTransaction.credit_amount).label("total_credit"))
        .filter(GatewayTransaction.gateway == "gateway_a",
                GatewayTransaction.txn_type.in_(["settlement", "offer_settlement"]))
        .group_by(GatewayTransaction.txn_type, GatewayTransaction.currency).all()
    )
    gwb_payout = (
        db.query(GatewayTransaction.payout_id, GatewayTransaction.currency,
                 func.count(GatewayTransaction.id).label("count"),
                 func.sum(GatewayTransaction.net_amount).label("total_net"),
                 func.sum(case((GatewayTransaction.txn_type == "charge", 1), else_=0)).label("charge_count"))
        .filter(GatewayTransaction.gateway == "gateway_b")
        .group_by(GatewayTransaction.payout_id, GatewayTransaction.currency).all()
    )
    return {
        "monthly_settlement_metrics": monthly,
        "timing_data_note": (
            "Gateway A duration is transaction time to the ledger settled_at value. Gateway B durations use balance available_on or the source payout-effective timestamp. These are source-reported timings, not independently verified bank receipt. Months are assigned by transaction date; rows without a transaction date are omitted."
        ),
        "gateway_a_settlement_summary": [
            {"transaction_type": r.txn_type, "currency": r.currency,
             "settlement_records": r.count, "observed_credit": float(r.total_credit or 0)}
            for r in gwa_settled
        ],
        "gateway_b_payout_summary": {
            "total_payouts": len([r for r in gwb_payout if r.payout_id]),
            "charges_without_payout": sum(r.charge_count for r in gwb_payout if not r.payout_id),
            "amount_basis": "Sum of imported balance transaction net amounts grouped by payout ID and currency; independent payout transfer amounts are not present in the supplied dataset.",
            "sample_payouts": [
                {"payout_id": r.payout_id, "currency": r.currency,
                 "balance_record_count": r.count, "charge_count": r.charge_count,
                 "total_net": float(r.total_net or 0)}
                for r in gwb_payout[:10] if r.payout_id
            ],
        },
    }
