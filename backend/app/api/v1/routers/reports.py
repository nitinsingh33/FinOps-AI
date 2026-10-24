"""Reports generation and CSV export endpoints."""
from __future__ import annotations

import csv
import io
import uuid
from html import escape
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import ReconciliationException, Payment, GatewayTransaction, Refund

router = APIRouter()


@router.get("/reports/executive-summary", response_class=HTMLResponse)
def executive_summary(db: Session = Depends(get_db)):
    """A concise, printable summary backed only by persisted source data."""
    from app.services.analytics_service import get_gateway_cost_analysis, get_overview_stats, get_settlement_analysis
    from app.models.models import PricingRule, ReconciliationRun, SavingsScenario

    data = get_overview_stats(db)
    costs = get_gateway_cost_analysis(db)
    settlements = get_settlement_analysis(db)
    run = db.query(ReconciliationRun).filter_by(status="completed").order_by(ReconciliationRun.created_at.desc()).first()

    monthly_rows = []
    for row in costs.get("monthly_breakdowns", [])[-6:]:
        cost = (f"{row['observed_cost_currency']} {row['observed_cost']:,.2f}"
                if row.get("observed_cost") is not None else
                "Incomplete observed amounts" if row.get("observed_cost_unavailable_reason") == "missing_amounts"
                else "Fee/tax currencies differ")
        monthly_rows.append(
            f"<tr><td>{escape(row['month'])}</td><td>{escape(row['gateway'])}</td>"
            f"<td>{row['transaction_count']:,}</td>"
            f"<td>{escape(row['currency'])} {row['gross_volume']:,.2f}</td>"
            f"<td>{escape(row['fee_currency'])} {row['observed_fees']:,.2f}"
            f" ({row['fee_records_missing_amount']} missing)</td>"
            f"<td>{escape(row['tax_currency'])} {row['observed_tax']:,.2f} ({row['tax_records_missing_amount']} missing); cost {escape(cost)}</td></tr>"
        )
    monthly_table = "".join(monthly_rows) or '<tr><td colspan="6">No monthly data available</td></tr>'

    timing_rows = []
    for row in settlements.get("monthly_settlement_metrics", [])[-6:]:
        timing = "—" if row["median_hours"] is None else f"{row['median_hours']:,.1f} h median"
        timing_rows.append(
            f"<tr><td>{escape(row['month'])}</td><td>{escape(row['gateway'])}</td>"
            f"<td>{escape(row['currency'])}</td><td>{escape(row['timing_basis'])}</td>"
            f"<td>{row['timed_rows']}/{row['source_rows']} timed · {escape(timing)}; "
            f"{row['explicitly_unsettled']} unsettled, {row['completion_time_unsettled_conflict']} time/status conflict</td></tr>"
        )
    timing_table = "".join(timing_rows) or '<tr><td colspan="5">No dated settlement evidence available</td></tr>'

    latest = (f"{run.id[:8]} · {run.matched_records or 0} matched · {run.exception_count or 0} exceptions · {run.completed_at.isoformat() if run.completed_at else 'completed'}"
              if run else "No completed reconciliation run")
    exposure = {}
    if run:
        for exception in db.query(ReconciliationException).filter_by(run_id=run.id).all():
            if exception.currency and exception.amount_at_stake is not None:
                exposure[exception.currency] = exposure.get(exception.currency, 0.0) + float(exception.amount_at_stake)
    exposure_text = ("; ".join(f"{escape(currency)} {amount:,.2f}" for currency, amount in sorted(exposure.items()))
                     if exposure else "No amount-at-stake values available")
    if exposure:
        exposure_text += " (flags can overlap; not a net loss total)"

    scenario = db.query(SavingsScenario).order_by(SavingsScenario.created_at.desc()).first()
    scenario_text = "No saved pricing scenario. No routing recommendation can be made."
    if scenario and scenario.estimated_difference is not None:
        diff = float(scenario.estimated_difference)
        lower_cost_gateway = scenario.alternative_gateway if diff > 0 else scenario.current_gateway
        scenario_text = (
            f"Latest scenario “{escape(scenario.name)}”: estimated difference "
            f"{escape(scenario.currency)} {abs(diff):,.2f} in favor of {escape(lower_cost_gateway)} for its stated volume. "
            "Estimate only; not confirmed savings or a routing recommendation."
        )
    elif scenario:
        scenario_text = "Latest saved scenario is incomplete; comparable estimates are unavailable."
    has_rules = db.query(PricingRule).count() > 0
    routing_note = ("Pricing inputs have no independently verified contract evidence; confirm signed rates before acting."
                    if has_rules else "No pricing rules exist, so no reliable gateway recommendation is available.")

    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><title>FinOps AI Executive Summary</title>
    <style>body{{font:11px Arial,sans-serif;color:#172033;margin:22px}}h1{{font-size:21px;margin-bottom:3px}}h2{{font-size:14px;margin:12px 0 4px}}.muted{{color:#526079}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0}}.tile{{border:1px solid #d7deea;border-radius:6px;padding:8px}}.value{{font-size:18px;font-weight:bold;margin-top:3px}}table{{border-collapse:collapse;width:100%;margin-top:4px;font-size:10px}}td,th{{padding:5px;border-bottom:1px solid #d7deea;text-align:left}}.note{{margin-top:9px;padding:8px;background:#eef4ff}}@page{{size:A4 portrait;margin:10mm}}@media print{{body{{margin:0}}}}</style></head><body>
    <h1>FinOps AI · Executive Summary</h1><div class="muted">Generated from imported database records. Figures stay in source currencies.</div>
    <div class="grid"><div class="tile">Payment records<div class="value">{data.get('total_payments', 0):,}</div></div><div class="tile">Gateway ledger records<div class="value">{data.get('total_transactions', 0):,}</div></div><div class="tile">Refund records<div class="value">{data.get('total_refunds', 0):,}</div></div><div class="tile">Open exceptions<div class="value">{data.get('open_exceptions', 0):,}</div></div></div>
    <h2>Observed monthly cost (latest 6 groups)</h2><table><thead><tr><th>Month</th><th>Gateway</th><th>Transactions</th><th>Gross</th><th>Observed fees</th><th>Observed tax and cost</th></tr></thead><tbody>{monthly_table}</tbody></table>
    <h2>Settlement timing (latest 6 source groups)</h2><table><thead><tr><th>Month</th><th>Gateway</th><th>Currency</th><th>Source timing</th><th>Coverage / median</th></tr></thead><tbody>{timing_table}</tbody></table>
    <h2>Reconciliation and exceptions</h2><p>{escape(latest)}. Amount at stake by currency: {exposure_text}.</p>
    <h2>Savings scenario and routing</h2><p>{scenario_text} {escape(routing_note)}</p>
    <div class="note">Fees and taxes are source-observed, not verified against contracts. Missing amounts are not zero. Gateway B availability and payout-effective times are not independent bank evidence; no separate payout transfer ledger was supplied. Exception flags can overlap. Scenario results are estimates, never confirmed savings.</div>
    </body></html>""")


@router.get("/reports/exceptions/download")
def download_exceptions_csv(
    gateway: str = Query(None),
    category: str = Query(None),
    review_status: str = Query(None),
    severity: str = Query(None),
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
    if severity:
        q = q.filter(ReconciliationException.severity == severity)
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
    return Response(
        content=output.getvalue(),
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
