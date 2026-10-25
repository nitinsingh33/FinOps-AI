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
    """A concise, printable finance brief backed by persisted source data."""
    from app.services.analytics_service import get_gateway_cost_analysis, get_overview_stats, get_settlement_analysis
    from app.models.models import PricingRule

    data = get_overview_stats(db)
    costs = get_gateway_cost_analysis(db)
    settlements = get_settlement_analysis(db)
    monthly = costs.get("monthly_breakdowns", [])
    settlement_rows = settlements.get("monthly_settlement_metrics", [])
    months = sorted({row["month"] for row in monthly} | {row["month"] for row in settlement_rows})
    period = f"{months[0]} – {months[-1]}" if months else "No dated imported records"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    groups: dict[tuple[str, str], list[dict]] = {}
    for row in monthly:
        groups.setdefault((row["month"], row["gateway"]), []).append(row)
    settlement_groups: dict[tuple[str, str], list[dict]] = {}
    for row in settlement_rows:
        settlement_groups.setdefault((row["month"], row["gateway"]), []).append(row)

    # Missing gross values are not available from the analytics aggregate, so
    # count them from the same source records for explicit display and rate safety.
    gross_missing: dict[tuple[str, str, str], int] = {}
    for gateway, query in (
        ("gateway_a", db.query(Payment.transacted_at, Payment.currency, Payment.gross_amount).filter(
            Payment.gateway == "gateway_a", Payment.status == "captured")),
        ("gateway_b", db.query(GatewayTransaction.transacted_at, GatewayTransaction.currency, GatewayTransaction.gross_amount).filter(
            GatewayTransaction.gateway == "gateway_b", GatewayTransaction.txn_type == "charge")),
    ):
        for transacted_at, currency, amount in query.all():
            if transacted_at and amount is None:
                key = (transacted_at.strftime("%Y-%m"), gateway, currency)
                gross_missing[key] = gross_missing.get(key, 0) + 1

    performance_rows = []
    all_groups = sorted(set(groups) | set(settlement_groups))
    for month, gateway in all_groups[-5:]:
        rows = groups.get((month, gateway), [])
        currency_groups: dict[str, list[dict]] = {}
        for row in rows:
            currency_groups.setdefault(row["currency"], []).append(row)
        currency = max(
            currency_groups,
            key=lambda code: (sum(row["gross_volume"] for row in currency_groups[code]), code),
            default=None,
        )
        primary_rows = currency_groups.get(currency, []) if currency else []
        tx_count = sum(row["transaction_count"] for row in primary_rows)
        tx_count_text = f"{tx_count:,}" if primary_rows else "—"
        gross = sum(row["gross_volume"] for row in primary_rows)
        missing_gross = gross_missing.get((month, gateway, currency), 0) if currency else 0
        gross_text = f"{escape(currency)} {gross:,.2f}" if currency else "—"
        if missing_gross:
            gross_text += f" ({missing_gross} missing)"

        fee_currencies = {row["fee_currency"] for row in primary_rows}
        fee_currency = next(iter(fee_currencies)) if len(fee_currencies) == 1 else None
        fee_missing = sum(row["fee_records_missing_amount"] for row in primary_rows)
        fee = sum(row["observed_fees"] for row in primary_rows)
        if not primary_rows:
            fee_text = "—"
        elif fee_currency:
            fee_text = f"{escape(fee_currency)} {fee:,.2f}" + (f" ({fee_missing} missing)" if fee_missing else "")
        else:
            fee_text = "Multiple currencies"
        rate = None
        if currency and fee_currency == currency and fee_missing == 0 and missing_gross == 0 and gross > 0:
            rate = fee / gross * 100
        rate_text = f"{rate:.3f}%" if rate is not None else "—"

        basis = "balance available_on" if gateway == "gateway_b" else "transaction settled_at"
        timings = [
            row for row in settlement_groups.get((month, gateway), [])
            if row["currency"] == currency and row["timing_basis"] == basis
        ]
        timing = max(timings, key=lambda row: row["source_rows"]) if timings else None
        median_text = f"{timing['median_hours']:,.1f} h" if timing and timing.get("median_hours") is not None else "—"
        performance_rows.append(
            f"<tr><td>{escape(gateway.replace('_', ' ').title())} · {escape(month)}</td>"
            f"<td class=\"num\">{tx_count_text}</td><td class=\"num\">{gross_text}</td>"
            f"<td class=\"num\">{fee_text}</td><td class=\"num\">{rate_text}</td>"
            f"<td class=\"num\">{median_text}</td></tr>"
        )
    performance_table = "".join(performance_rows) or '<tr><td colspan="6">No monthly payment-cost data available</td></tr>'

    open_count = data.get("open_exceptions", 0)
    open_categories = data.get("open_exceptions_by_category", {})
    top_categories = [name for name, _ in sorted(open_categories.items(), key=lambda item: (-item[1], item[0]))[:2]]
    category_text = ", ".join(escape(name) for name in top_categories) or "no open categories recorded"
    reconciliation_finding = (
        f"Open items are led by {category_text}. These are investigation flags, not confirmed losses."
        if top_categories else "No open reconciliation investigation items are recorded."
    )

    b_timing = [
        row for row in settlement_rows
        if row["gateway"] == "gateway_b" and row["timing_basis"] == "balance available_on"
    ]
    b_unsettled = sum(row["explicitly_unsettled"] for row in b_timing)
    b_source_count = sum(row["source_rows"] for row in b_timing)
    representative = max(b_timing, key=lambda row: row["source_rows"]) if b_timing else None
    if representative and representative.get("median_hours") is not None:
        settlement_finding = (
            f"Gateway B’s largest dated group ({escape(representative['month'])}, {escape(representative['currency'])}) "
            f"shows a {representative['median_hours']:,.1f} h median; {b_unsettled:,} of {b_source_count:,} source rows are marked unsettled."
        )
    elif b_timing:
        settlement_finding = f"Gateway B has {b_unsettled:,} of {b_source_count:,} source rows marked unsettled; median timing is unavailable."
    else:
        settlement_finding = "No dated Gateway B settlement timing is available in the imported records."

    cost_finding = "Fees are source-observed; without signed pricing, contractual overcharges cannot be confirmed."
    if db.query(PricingRule).count() == 0:
        cost_finding += " Savings estimates are unavailable until pricing rules are configured."

    kpis = (
        ("Payment records", data.get("total_payments", 0)),
        ("Gateway ledger records", data.get("total_transactions", 0)),
        ("Open investigation items", open_count),
        ("Refund records", data.get("total_refunds", 0)),
    )
    kpi_html = "".join(
        f'<div class="kpi"><div class="kpi-label">{escape(label)}</div><div class="kpi-value">{value:,}</div></div>'
        for label, value in kpis
    )
    finding_html = "".join(
        f'<article class="finding"><div class="tag">{escape(label)}</div><p>{text}</p></article>'
        for label, text in (
            ("Settlement", settlement_finding),
            ("Reconciliation", reconciliation_finding),
            ("Cost", cost_finding),
        )
    )
    actions = (
        "Review Gateway B settlement exceptions against independent payout evidence.",
        "Obtain signed gateway pricing and validate fee components.",
        "Investigate the highest-priority reconciliation exceptions.",
    )
    actions_html = "".join(f"<li>{escape(action)}</li>" for action in actions)
    links = '<a href="/analytics">Detailed Analytics</a> · <a href="/reconciliation">Detailed Reconciliation</a>'

    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><title>FinOps AI — Payment Gateway Executive Summary</title>
    <style>
      *{{box-sizing:border-box}}body{{margin:0;background:#fff;color:#172b4d;font:10pt/1.42 Arial,sans-serif}}main{{max-width:1120px;margin:0 auto;padding:25px 30px}}header{{border-bottom:2px solid #dce6f3;padding-bottom:12px}}h1{{font-size:21pt;line-height:1.15;margin:0 0 6px;color:#10243e}}.sub{{color:#52657d;font-size:9pt}}h2{{font-size:12pt;margin:19px 0 9px;color:#183a63}}.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:17px 0 20px}}.kpi{{padding:12px 14px;border:1px solid #dce5ef;border-top:3px solid #4d83bd;border-radius:4px}}.kpi-label{{font-size:8pt;color:#53677f}}.kpi-value{{font-size:18pt;font-weight:700;margin-top:3px}}.findings{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}}.finding{{border-left:2px solid #8db3da;padding:1px 0 1px 11px}}.tag{{font-size:8pt;font-weight:bold;color:#315e8d;text-transform:uppercase;letter-spacing:.05em}}.finding p{{margin:4px 0 0}}table{{width:100%;border-collapse:collapse;table-layout:fixed;font-size:9pt}}th{{font-size:8pt;color:#53677f;font-weight:600;border-bottom:1px solid #bac9da;padding:8px 7px;text-align:left}}td{{padding:9px 7px;border-bottom:1px solid #e5ebf2;vertical-align:top;overflow-wrap:anywhere}}.num{{text-align:right;font-variant-numeric:tabular-nums}}.comparison th:nth-child(1){{width:20%}}.comparison th:nth-child(2){{width:10%}}.comparison th:nth-child(3){{width:22%}}.comparison th:nth-child(4){{width:20%}}.comparison th:nth-child(5){{width:13%}}.comparison th:nth-child(6){{width:15%}}.actions{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin:7px 0 18px;padding:0;list-style:none;counter-reset:action}}.actions li{{counter-increment:action;border-top:1px solid #dce5ef;padding-top:8px;color:#263d59}}.actions li:before{{content:counter(action) ". ";font-weight:bold;color:#3974ac}}footer{{border-top:1px solid #dce5ef;padding-top:8px;color:#53677f;font-size:8pt}}a{{color:#285e98;text-decoration:none}}@page{{size:A4 landscape;margin:13mm}}@media print{{main{{max-width:none;padding:0}}h2{{margin-top:16px}}.kpis{{margin:12px 0 15px}}thead{{display:table-header-group}}tr{{break-inside:avoid}}}}
    </style></head><body><main>
    <header><h1>FinOps AI — Payment Gateway Executive Summary</h1><div class="sub">Reporting period: {escape(period)} · Imported payment, gateway ledger and refund records · Source currency amounts</div></header>
    <section class="kpis">{kpi_html}</section>
    <section><h2>Key findings</h2><div class="findings">{finding_html}</div></section>
    <section><h2>Gateway comparison</h2><table class="comparison"><thead><tr><th>Gateway · Month</th><th class="num">Txns¹</th><th class="num">Gross¹</th><th class="num">Observed fees²</th><th class="num">Effective rate³</th><th class="num">Median settlement⁴</th></tr></thead><tbody>{performance_table}</tbody></table><div class="sub">Up to five latest month/gateway groups, shown in the primary gross-volume currency. Full currency details: {links}.</div></section>
    <section><h2>Recommended next steps</h2><ol class="actions">{actions_html}</ol></section>
    <footer>¹ Primary currency group only; missing gross values are shown. ² Observed fee values; missing amounts are shown. ³ Shown only when fee and payment currencies match and amounts are complete. ⁴ Source-reported timing, not independent bank evidence. Contract pricing and independent bank payout evidence were not supplied; savings and overcharges are not confirmed. {links}. Generated {escape(generated_at)}.</footer>
    </main></body></html>""")


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
