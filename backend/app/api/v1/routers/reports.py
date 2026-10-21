"""Reports generation and CSV export endpoints."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import ReconciliationException, Payment, GatewayTransaction, Refund

router = APIRouter()


@router.get("/reports/exceptions/download")
def download_exceptions_csv(
    gateway: str = Query(None),
    category: str = Query(None),
    review_status: str = Query(None),
    db: Session = Depends(get_db),
):
    """Download reconciliation exceptions as CSV."""
    q = db.query(ReconciliationException)
    if gateway:
        q = q.filter(ReconciliationException.gateway == gateway)
    if category:
        q = q.filter(ReconciliationException.category == category)
    if review_status:
        q = q.filter(ReconciliationException.review_status == review_status)
    exceptions = q.order_by(ReconciliationException.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "exception_id", "run_id", "category", "severity", "gateway", "currency",
        "amount_at_stake", "amount_difference", "expected_value", "observed_value",
        "description", "review_status", "source_payment_id", "source_txn_id",
        "source_refund_id", "created_at",
    ])
    for e in exceptions:
        writer.writerow([
            e.id, e.run_id, e.category, e.severity, e.gateway, e.currency or "",
            str(e.amount_at_stake or ""), str(e.amount_difference or ""),
            str(e.expected_value or ""), str(e.observed_value or ""),
            e.description, e.review_status,
            e.source_payment_id or "", e.source_txn_id or "", e.source_refund_id or "",
            e.created_at.isoformat(),
        ])

    output.seek(0)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"reconciliation_exceptions_{timestamp}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/payments/download")
def download_payments_csv(
    gateway: str = Query(None),
    currency: str = Query(None),
    status: str = Query(None),
    db: Session = Depends(get_db),
):
    """Download payment records as CSV."""
    q = db.query(Payment)
    if gateway:
        q = q.filter(Payment.gateway == gateway)
    if currency:
        q = q.filter(Payment.currency == currency)
    if status:
        q = q.filter(Payment.status == status)
    payments = q.order_by(Payment.transacted_at.desc()).limit(50000).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "gateway_payment_id", "gateway", "status", "currency", "gross_amount",
        "fee", "fee_currency", "tax", "tax_currency", "amount_refunded",
        "payment_method", "is_international", "is_captured", "card_network",
        "card_type", "country", "transacted_at",
    ])
    for p in payments:
        writer.writerow([
            p.gateway_payment_id, p.gateway, p.status, p.currency,
            str(p.gross_amount or ""), str(p.fee or ""), p.fee_currency or "",
            str(p.tax or ""), p.tax_currency or "", str(p.amount_refunded or ""),
            p.payment_method or "", p.is_international, p.is_captured,
            p.card_network or "", p.card_type or "", p.country or "",
            p.transacted_at.isoformat() if p.transacted_at else "",
        ])

    output.seek(0)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="payments_{timestamp}.csv"'},
    )


@router.get("/reports/transactions/download")
def download_transactions_csv(
    gateway: str = Query(None),
    txn_type: str = Query(None),
    db: Session = Depends(get_db),
):
    """Download gateway transaction records as CSV."""
    q = db.query(GatewayTransaction)
    if gateway:
        q = q.filter(GatewayTransaction.gateway == gateway)
    if txn_type:
        q = q.filter(GatewayTransaction.txn_type == txn_type)
    txns = q.order_by(GatewayTransaction.transacted_at.desc()).limit(50000).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "gateway_txn_id", "gateway", "txn_type", "currency", "gross_amount",
        "fee", "tax", "net_amount", "credit_amount", "debit_amount",
        "settlement_id", "is_settled", "payout_id", "country",
        "card_network", "card_brand", "transacted_at", "settled_at",
    ])
    for t in txns:
        writer.writerow([
            t.gateway_txn_id, t.gateway, t.txn_type, t.currency,
            str(t.gross_amount or ""), str(t.fee or ""), str(t.tax or ""),
            str(t.net_amount or ""), str(t.credit_amount or ""), str(t.debit_amount or ""),
            t.settlement_id or "", t.is_settled, t.payout_id or "",
            t.country or "", t.card_network or "", t.card_brand or "",
            t.transacted_at.isoformat() if t.transacted_at else "",
            t.settled_at.isoformat() if t.settled_at else "",
        ])

    output.seek(0)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="transactions_{timestamp}.csv"'},
    )


@router.get("/reports/refunds/download")
def download_refunds_csv(db: Session = Depends(get_db)):
    refunds = db.query(Refund).order_by(Refund.refunded_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["gateway_refund_id", "gateway", "gateway_payment_id", "status", "amount", "currency", "arn", "refunded_at"])
    for r in refunds:
        writer.writerow([r.gateway_refund_id, r.gateway, r.gateway_payment_id or "", r.status, str(r.amount), r.currency, r.arn or "", r.refunded_at.isoformat() if r.refunded_at else ""])
    output.seek(0)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="refunds_{timestamp}.csv"'},
    )
