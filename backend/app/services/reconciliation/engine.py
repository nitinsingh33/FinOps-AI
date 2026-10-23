"""
Reconciliation Engine — deterministic, explainable matching.

Matching hierarchy (strongest first):
1. Exact gateway payment ID match (GatewayA payment ↔ GatewayA transaction)
2. Order ID match
3. Settlement ID match
4. Amount + currency + date proximity (fallback, lower confidence)

Scope: This engine reconciles within each gateway's own payment vs transaction ledger,
and separately analyses Gateway B balance transactions for payout completeness.

Cross-gateway comparison is out of scope for transaction-level matching because
the two gateways serve different customer cohorts with different currencies and IDs.

Financial rules applied:
- Expected net (payment type only) = gross - fee - tax
- Do NOT apply net formula to refunds, payouts, disputes, or adjustments
- Amounts from different currencies are NEVER added
- Missing amounts are NEVER treated as zero
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.models import (
    ExceptionCategory,
    GatewayTransaction,
    MatchConfidence,
    MatchMethod,
    Payment,
    ReconciliationException,
    ReconciliationMatch,
    ReconciliationRun,
    ReconciliationStatus,
    Refund,
    ReviewStatus,
)

PAYMENT_TYPES = {"payment"}
REFUND_TYPES = {"refund"}
PAYOUT_TYPES = {"payout", "transfer", "automatic_payout"}
SETTLEMENT_DELAY_DAYS_THRESHOLD = 7  # Flag if settlement > 7 days after transaction


@dataclass
class ReconciliationContext:
    run_id: str
    matched: List[Dict] = field(default_factory=list)
    exceptions: List[Dict] = field(default_factory=list)
    matched_payment_ids: set = field(default_factory=set)
    matched_txn_ids: set = field(default_factory=set)


def _two_decimal(v: Optional[Decimal]) -> Optional[Decimal]:
    if v is None:
        return None
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _add_exception(
    ctx: ReconciliationContext,
    run_id: str,
    category: str,
    gateway: str,
    description: str,
    currency: Optional[str] = None,
    amount_at_stake: Optional[Decimal] = None,
    amount_difference: Optional[Decimal] = None,
    expected_value: Optional[Decimal] = None,
    observed_value: Optional[Decimal] = None,
    evidence: Optional[Dict] = None,
    source_payment_id: Optional[str] = None,
    source_txn_id: Optional[str] = None,
    source_refund_id: Optional[str] = None,
    severity: str = "medium",
) -> None:
    ctx.exceptions.append({
        "id": str(uuid.uuid4()),
        "run_id": run_id,
        "category": category,
        "severity": severity,
        "gateway": gateway,
        "currency": currency,
        "amount_at_stake": amount_at_stake,
        "amount_difference": amount_difference,
        "expected_value": expected_value,
        "observed_value": observed_value,
        "description": description,
        "evidence": evidence or {},
        "source_payment_id": source_payment_id,
        "source_txn_id": source_txn_id,
        "source_refund_id": source_refund_id,
        "review_status": ReviewStatus.OPEN,
    })


def reconcile_gwa(db: Session, ctx: ReconciliationContext) -> None:
    """
    Gateway A reconciliation:
    - Match payments (from payments export) against transactions (from ledger export)
    - Check fee/tax consistency
    - Detect unsettled, delayed settlements, net mismatches
    - Match refunds against payments
    """
    # Load Gateway A payments
    payments = (
        db.query(Payment)
        .filter_by(gateway="gateway_a")
        .all()
    )
    # Load Gateway A transactions (only payment-type entries)
    txns = (
        db.query(GatewayTransaction)
        .filter(
            GatewayTransaction.gateway == "gateway_a",
            GatewayTransaction.txn_type.in_(list(PAYMENT_TYPES))
        )
        .all()
    )
    # Load Gateway A refunds
    refunds = (
        db.query(Refund)
        .filter_by(gateway="gateway_a")
        .all()
    )

    # Index transactions by their entity_id (which is the payment ID for payment-type txns)
    txn_by_payment_id: Dict[str, GatewayTransaction] = {}
    for txn in txns:
        if txn.gateway_txn_id:  # entity_id is stored as gateway_txn_id
            txn_by_payment_id[txn.gateway_txn_id] = txn

    # Index refunds by payment_id
    refund_by_payment_id: Dict[str, List[Refund]] = {}
    for r in refunds:
        if r.gateway_payment_id:
            refund_by_payment_id.setdefault(r.gateway_payment_id, []).append(r)

    unmatched_payment_ids = set()

    for payment in payments:
        pid = payment.gateway_payment_id

        # --- Step 1: Match payment → transaction by payment ID ---
        matched_txn = txn_by_payment_id.get(pid)

        if matched_txn:
            ctx.matched_payment_ids.add(payment.id)
            ctx.matched_txn_ids.add(matched_txn.id)

            evidence = {
                "match_method": MatchMethod.EXACT_ID,
                "payment_id": pid,
                "payment_gross": str(payment.gross_amount),
                "payment_currency": payment.currency,
                "txn_gross": str(matched_txn.gross_amount),
                "txn_currency": matched_txn.currency,
                "txn_credit": str(matched_txn.credit_amount),
                "payment_fee": str(payment.fee),
                "txn_fee": str(matched_txn.fee),
                "payment_tax": str(payment.tax),
                "txn_tax": str(matched_txn.tax),
            }

            ctx.matched.append({
                "id": str(uuid.uuid4()),
                "run_id": ctx.run_id,
                "match_method": MatchMethod.EXACT_ID,
                "confidence": MatchConfidence.HIGH,
                "payment_id": pid,
                "gateway_txn_id": matched_txn.gateway_txn_id,
                "match_evidence": evidence,
                "amount_difference": None,
                "currency": payment.currency,
            })

            if payment.currency != matched_txn.currency:
                _add_exception(
                    ctx, ctx.run_id, ExceptionCategory.CURRENCY_MISMATCH, "gateway_a",
                    f"Currency mismatch for payment {pid}: payment export={payment.currency}, transaction ledger={matched_txn.currency}. Amount comparison was skipped.",
                    evidence=evidence, source_payment_id=pid,
                    source_txn_id=matched_txn.gateway_txn_id, severity="high",
                )

            # --- Step 2: Fee discrepancy check (only for captured INR payments) ---
            # The transaction file uses INR; the payment file may have other currencies
            # We only compare fees when both are in the same currency context
            if (payment.fee_currency == matched_txn.currency
                    and payment.fee is not None and matched_txn.fee is not None):
                fee_diff = abs(payment.fee - matched_txn.fee)
                if fee_diff > Decimal("1.00"):  # 1 INR tolerance for rounding
                    _add_exception(
                        ctx, ctx.run_id,
                        ExceptionCategory.FEE_DISCREPANCY,
                        "gateway_a",
                        f"Fee mismatch for payment {pid}: "
                            f"payments_export={payment.fee} {payment.fee_currency}, "
                            f"transactions_export={matched_txn.fee} {matched_txn.currency}, "
                            f"difference={fee_diff} {matched_txn.currency}",
                        currency=matched_txn.currency,
                        amount_difference=fee_diff,
                        expected_value=matched_txn.fee,
                        observed_value=payment.fee,
                        evidence=evidence,
                        source_payment_id=pid,
                        source_txn_id=matched_txn.gateway_txn_id,
                        severity="medium",
                    )

            # --- Step 3: Expected net check (only payment-type, same currency) ---
            # Formula: Expected net = gross - fee - tax
            # Only valid when all three values are available and currency is consistent
            if (matched_txn.currency == "INR"
                    and matched_txn.gross_amount is not None
                    and matched_txn.fee is not None
                    and matched_txn.tax is not None
                    and matched_txn.credit_amount is not None):
                expected_net = matched_txn.gross_amount - matched_txn.fee - matched_txn.tax
                actual_credit = matched_txn.credit_amount
                net_diff = abs(expected_net - actual_credit)
                if net_diff > Decimal("2.00"):  # 2 INR tolerance
                    _add_exception(
                        ctx, ctx.run_id,
                        ExceptionCategory.NET_AMOUNT_MISMATCH,
                        "gateway_a",
                        f"Net amount mismatch for payment {pid}: "
                        f"expected_net={expected_net} INR (gross-fee-tax), "
                        f"actual_credit={actual_credit} INR, "
                        f"difference={net_diff} INR",
                        currency="INR",
                        amount_difference=net_diff,
                        expected_value=expected_net,
                        observed_value=actual_credit,
                        evidence=evidence,
                        source_payment_id=pid,
                        source_txn_id=matched_txn.gateway_txn_id,
                        severity="medium",
                    )

            # --- Step 4: Settlement delay check ---
            if (matched_txn.transacted_at and matched_txn.settled_at
                    and matched_txn.is_settled):
                delay = matched_txn.settled_at - matched_txn.transacted_at
                if delay.days > SETTLEMENT_DELAY_DAYS_THRESHOLD:
                    _add_exception(
                        ctx, ctx.run_id,
                        ExceptionCategory.SETTLEMENT_DELAY,
                        "gateway_a",
                        f"Settlement delayed {delay.days} days for payment {pid} "
                        f"(transacted={matched_txn.transacted_at.date()}, "
                        f"settled={matched_txn.settled_at.date()})",
                        currency=matched_txn.currency,
                        amount_at_stake=matched_txn.credit_amount,
                        evidence={
                            "payment_id": pid,
                            "transacted_at": str(matched_txn.transacted_at),
                            "settled_at": str(matched_txn.settled_at),
                            "delay_days": delay.days,
                        },
                        source_payment_id=pid,
                        source_txn_id=matched_txn.gateway_txn_id,
                        severity="low",
                    )

            # --- Step 5: Unsettled check ---
            if matched_txn.is_settled is False and payment.status == "captured":
                _add_exception(
                    ctx, ctx.run_id,
                    ExceptionCategory.UNSETTLED_TRANSACTION,
                    "gateway_a",
                    f"Captured payment {pid} has no settlement recorded",
                    currency=matched_txn.currency,
                    amount_at_stake=matched_txn.credit_amount,
                    evidence={"payment_id": pid},
                    source_payment_id=pid,
                    source_txn_id=matched_txn.gateway_txn_id,
                    severity="medium",
                )

        else:
            # No matching transaction found
            unmatched_payment_ids.add(pid)
            if payment.status == "captured":
                _add_exception(
                    ctx, ctx.run_id,
                    ExceptionCategory.MISSING_GATEWAY_TXN,
                    "gateway_a",
                    f"Captured payment {pid} has no corresponding gateway transaction record",
                    currency=payment.currency,
                    amount_at_stake=payment.gross_amount,
                    evidence={"payment_id": pid, "status": payment.status},
                    source_payment_id=pid,
                    severity="high",
                )

        # --- Step 6: Refund matching (with cumulative partial refund aggregation) ---
        linked_refunds = refund_by_payment_id.get(pid, [])
        if linked_refunds and payment.amount_refunded is not None:
            # Group refunds by currency to strictly preserve currency boundaries
            refunds_by_curr: Dict[str, List[Refund]] = {}
            for r in linked_refunds:
                if r.status.lower() not in ("failed", "cancelled"):
                    refunds_by_curr.setdefault(r.currency, []).append(r)

            for ref_curr, curr_refunds in refunds_by_curr.items():
                if ref_curr == payment.currency:
                    # Aggregate all valid partial refunds for this payment
                    total_refunded_records = sum((r.amount for r in curr_refunds), Decimal(0))
                    refund_diff = abs(total_refunded_records - payment.amount_refunded)
                    if refund_diff > Decimal("1.00"):
                        _add_exception(
                            ctx, ctx.run_id,
                            ExceptionCategory.REFUND_AMOUNT_MISMATCH,
                            "gateway_a",
                            f"Cumulative refund mismatch for payment {pid}: "
                            f"sum_of_refund_records={total_refunded_records} {ref_curr} ({len(curr_refunds)} refund(s)), "
                            f"payment.amount_refunded={payment.amount_refunded} {payment.currency}, "
                            f"difference={refund_diff}",
                            currency=ref_curr,
                            amount_difference=refund_diff,
                            expected_value=payment.amount_refunded,
                            observed_value=total_refunded_records,
                            evidence={
                                "refund_ids": [r.gateway_refund_id for r in curr_refunds],
                                "payment_id": pid,
                                "refund_count": len(curr_refunds),
                            },
                            source_payment_id=pid,
                            source_refund_id=curr_refunds[0].gateway_refund_id if curr_refunds else None,
                            severity="medium",
                        )

    # Detect orphan/unmatched refunds referencing missing payments
    known_payment_ids = {p.gateway_payment_id for p in payments if p.gateway_payment_id}
    for r in refunds:
        if r.gateway_payment_id and r.gateway_payment_id not in known_payment_ids:
            _add_exception(
                ctx, ctx.run_id,
                ExceptionCategory.UNMATCHED_REFUND,
                "gateway_a",
                f"Refund {r.gateway_refund_id} references payment {r.gateway_payment_id} which does not exist in payments export",
                currency=r.currency,
                amount_at_stake=r.amount,
                evidence={"refund_id": r.gateway_refund_id, "referenced_payment_id": r.gateway_payment_id},
                source_refund_id=r.gateway_refund_id,
                severity="high",
            )

    # Unmatched transactions (in ledger but no payment record)
    for txn in txns:
        if txn.id not in ctx.matched_txn_ids:
            _add_exception(
                ctx, ctx.run_id,
                ExceptionCategory.MISSING_PAYMENT,
                "gateway_a",
                f"Transaction {txn.gateway_txn_id} in ledger has no corresponding payment record",
                currency=txn.currency,
                amount_at_stake=txn.gross_amount,
                evidence={"txn_id": txn.gateway_txn_id, "type": txn.txn_type},
                source_txn_id=txn.gateway_txn_id,
                severity="medium",
            )


def reconcile_gwb(db: Session, ctx: ReconciliationContext) -> None:
    """
    Gateway B reconciliation:
    - All records are balance_transactions
    - Check that charge-type records have a matching payout
    - Verify net = gross - fee for each record
    - Flag payout-less charge records
    - Note: GWB charge IDs (source_id = charge_id prefix bchg_) are internal to GWB.
             We do NOT cross-match with GWA payment IDs.
    """
    all_gwb = (
        db.query(GatewayTransaction)
        .filter(GatewayTransaction.gateway == "gateway_b")
        .all()
    )

    payout_ids_with_txns: set = set()
    for txn in all_gwb:
        if txn.payout_id:
            payout_ids_with_txns.add(txn.payout_id)

    for txn in all_gwb:
        # --- Net amount check ---
        if (txn.gross_amount is not None
                and txn.fee is not None
                and txn.net_amount is not None
                and txn.txn_type in {"charge", "payment"}):
            expected_net = txn.gross_amount - txn.fee
            net_diff = abs(expected_net - txn.net_amount)
            if net_diff > Decimal("1.00"):
                _add_exception(
                    ctx, ctx.run_id,
                    ExceptionCategory.NET_AMOUNT_MISMATCH,
                    "gateway_b",
                    f"GWB transaction {txn.gateway_txn_id}: "
                    f"expected_net={expected_net} (gross-fee), "
                    f"reported_net={txn.net_amount}, "
                    f"difference={net_diff}",
                    currency=txn.currency,
                    amount_difference=net_diff,
                    expected_value=expected_net,
                    observed_value=txn.net_amount,
                    evidence={
                        "txn_id": txn.gateway_txn_id,
                        "gross": str(txn.gross_amount),
                        "fee": str(txn.fee),
                        "reported_net": str(txn.net_amount),
                    },
                    source_txn_id=txn.gateway_txn_id,
                    severity="medium",
                )

        # --- Payout linkage check for charge-type records ---
        if txn.txn_type == "charge" and not txn.payout_id:
            _add_exception(
                ctx, ctx.run_id,
                ExceptionCategory.MISSING_SETTLEMENT,
                "gateway_b",
                f"GWB charge transaction {txn.gateway_txn_id} has no associated payout ID",
                currency=txn.currency,
                amount_at_stake=txn.net_amount,
                evidence={
                    "txn_id": txn.gateway_txn_id,
                    "gross": str(txn.gross_amount),
                    "available_on": str(txn.available_on),
                },
                source_txn_id=txn.gateway_txn_id,
                severity="low",
            )


def run_reconciliation(db: Session, run_id: str) -> ReconciliationRun:
    """
    Execute full reconciliation. Updates the ReconciliationRun record.
    """
    run = db.query(ReconciliationRun).filter_by(id=run_id).first()
    if not run:
        raise ValueError(f"ReconciliationRun {run_id} not found")

    run.status = ReconciliationStatus.RUNNING
    run.started_at = datetime.now(timezone.utc)
    db.flush()

    ctx = ReconciliationContext(run_id=run_id)

    try:
        reconcile_gwa(db, ctx)
        reconcile_gwb(db, ctx)
    except Exception as exc:
        run.status = ReconciliationStatus.FAILED
        run.error_message = str(exc)[:2000]
        run.completed_at = datetime.now(timezone.utc)
        db.flush()
        raise

    # Persist matches
    for m in ctx.matched:
        db.add(ReconciliationMatch(**m))

    # Persist exceptions
    for e in ctx.exceptions:
        db.add(ReconciliationException(**e))

    db.flush()

    # Summary by exception category and currency
    exception_summary: Dict[str, int] = {}
    for e in ctx.exceptions:
        exception_summary[e["category"]] = exception_summary.get(e["category"], 0) + 1

    # Amounts at stake by currency (only where currency is set)
    amounts_by_currency: Dict[str, Decimal] = {}
    for e in ctx.exceptions:
        if e.get("currency") and e.get("amount_at_stake"):
            curr = e["currency"]
            amounts_by_currency[curr] = amounts_by_currency.get(curr, Decimal(0)) + e["amount_at_stake"]

    # Load totals
    total_payments = db.query(Payment).filter_by(gateway="gateway_a").count()
    total_gwb = db.query(GatewayTransaction).filter_by(gateway="gateway_b").count()

    run.total_records = total_payments + total_gwb
    run.matched_records = len(ctx.matched)
    run.unmatched_records = len([e for e in ctx.exceptions
                                  if e["category"] in (
                                      ExceptionCategory.MISSING_GATEWAY_TXN,
                                      ExceptionCategory.MISSING_PAYMENT,
                                  )])
    run.ambiguous_records = 0  # No ambiguous matches in current rule set
    run.exception_count = len(ctx.exceptions)
    run.summary = {
        "exception_by_category": exception_summary,
        "amounts_at_stake_by_currency": {k: str(v) for k, v in amounts_by_currency.items()},
        "match_rate_pct": round(
            len(ctx.matched) / max(total_payments, 1) * 100, 1
        ),
        "rule_version": run.rule_version,
    }
    run.status = ReconciliationStatus.COMPLETED
    run.completed_at = datetime.now(timezone.utc)
    db.flush()
    return run
