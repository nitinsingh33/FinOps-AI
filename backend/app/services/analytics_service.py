"""
Analytics service — real calculations from the database.
No hardcoded values. All metrics are aggregated from imported records.
Currencies are never mixed in totals.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
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
    gwa_fees = (
        db.query(
            func.sum(Payment.fee).label("total_fee"),
            func.sum(Payment.tax).label("total_tax"),
        )
        .filter(Payment.gateway == "gateway_a", Payment.fee.isnot(None))
        .first()
    )
    result["gateway_a_fees_inr"] = {
        "total_fee": float(gwa_fees.total_fee or 0),
        "total_tax": float(gwa_fees.total_tax or 0),
        "currency": "INR",
        "note": "Gateway A fees and taxes are denominated in INR per gateway ledger",
    }

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
    result["open_exceptions"] = {r.category: r.count for r in open_exceptions}
    result["total_open_exceptions"] = sum(r.count for r in open_exceptions)

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
                    Payment.payment_method,
                    Payment.card_network,
                    func.count(Payment.id).label("count"),
                    func.sum(Payment.gross_amount).label("gross"),
                    func.sum(Payment.fee).label("fees"),
                    func.sum(Payment.tax).label("taxes"),
                )
                .filter(Payment.status == "captured", Payment.fee.isnot(None))
                .group_by(Payment.currency, Payment.payment_method, Payment.card_network)
                .all()
            )
            result["gateway_a"] = [
                {
                    "currency": r.currency,
                    "payment_method": r.payment_method,
                    "card_network": r.card_network,
                    "transaction_count": r.count,
                    "gross_volume": float(r.gross or 0),
                    "total_fees": float(r.fees or 0),
                    "total_taxes": float(r.taxes or 0),
                    "effective_fee_rate_pct": round(
                        float(r.fees) / float(r.gross) * 100, 4
                    ) if r.gross and float(r.gross) > 0 and r.fees else None,
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

    return result
