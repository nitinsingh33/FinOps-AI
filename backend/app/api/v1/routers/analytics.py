"""Analytics and gateway cost endpoints."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from app.db.session import get_db
from app.services.analytics_service import get_gateway_cost_analysis, get_overview_stats

router = APIRouter()


@router.get("/analytics/overview")
def overview(db: Session = Depends(get_db)):
    return get_overview_stats(db)


@router.get("/analytics/gateway-costs")
def gateway_costs(
    gateway: str = Query(None, description="Filter by gateway: gateway_a or gateway_b"),
    db: Session = Depends(get_db),
):
    return get_gateway_cost_analysis(db, gateway=gateway)


@router.get("/analytics/settlements")
def settlement_analysis(db: Session = Depends(get_db)):
    from app.models.models import GatewayTransaction, Settlement

    # Settlement status summary for Gateway A
    gwa_settled = (
        db.query(
            GatewayTransaction.txn_type,
            GatewayTransaction.currency,
            func.count(GatewayTransaction.id).label("count"),
            func.sum(GatewayTransaction.credit_amount).label("total_credit"),
        )
        .filter(GatewayTransaction.gateway == "gateway_a",
                GatewayTransaction.txn_type.in_(["settlement", "offer_settlement"]))
        .group_by(GatewayTransaction.txn_type, GatewayTransaction.currency)
        .all()
    )

    # Settlement payout summary for Gateway B
    gwb_payout = (
        db.query(
            GatewayTransaction.payout_id,
            GatewayTransaction.currency,
            func.count(GatewayTransaction.id).label("count"),
            func.sum(GatewayTransaction.net_amount).label("total_net"),
            func.sum(case((GatewayTransaction.txn_type == "charge", 1), else_=0)).label("charge_count"),
        )
        .filter(
            GatewayTransaction.gateway == "gateway_b",
        )
        .group_by(GatewayTransaction.payout_id, GatewayTransaction.currency)
        .all()
    )

    return {
        "gateway_a_settlement_summary": [
            {
                "transaction_type": r.txn_type,
                "currency": r.currency,
                "settlement_records": r.count,
                "observed_credit": float(r.total_credit or 0),
            }
            for r in gwa_settled
        ],
        "gateway_b_payout_summary": {
            "total_payouts": len([r for r in gwb_payout if r.payout_id]),
            "charges_without_payout": sum(r.charge_count for r in gwb_payout if not r.payout_id),
            "amount_basis": "Sum of imported balance transaction net amounts grouped by payout ID and currency; independent payout transfer amounts are not present in the supplied dataset.",
            "sample_payouts": [
                {
                    "payout_id": r.payout_id,
                    "currency": r.currency,
                    "balance_record_count": r.count,
                    "charge_count": r.charge_count,
                    "total_net": float(r.total_net or 0),
                }
                for r in gwb_payout[:10] if r.payout_id
            ],
        },
    }
