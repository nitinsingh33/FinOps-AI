"""Analytics and gateway cost endpoints."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

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
    from app.models.models import GatewayTransaction
    from sqlalchemy import func

    # Settlement status summary for Gateway A
    gwa_settled = (
        db.query(
            GatewayTransaction.is_settled,
            GatewayTransaction.currency,
            func.count(GatewayTransaction.id).label("count"),
            func.sum(GatewayTransaction.credit_amount).label("total_credit"),
        )
        .filter(GatewayTransaction.gateway == "gateway_a")
        .group_by(GatewayTransaction.is_settled, GatewayTransaction.currency)
        .all()
    )

    # Settlement payout summary for Gateway B
    gwb_payout = (
        db.query(
            GatewayTransaction.payout_id,
            func.count(GatewayTransaction.id).label("count"),
            func.sum(GatewayTransaction.net_amount).label("total_net"),
        )
        .filter(
            GatewayTransaction.gateway == "gateway_b",
            GatewayTransaction.txn_type == "charge",
        )
        .group_by(GatewayTransaction.payout_id)
        .limit(50)
        .all()
    )

    return {
        "gateway_a_settlement_summary": [
            {
                "is_settled": r.is_settled,
                "currency": r.currency,
                "count": r.count,
                "total_credit": float(r.total_credit or 0),
            }
            for r in gwa_settled
        ],
        "gateway_b_payout_summary": {
            "total_payouts": len([r for r in gwb_payout if r.payout_id]),
            "charges_without_payout": len([r for r in gwb_payout if not r.payout_id]),
            "sample_payouts": [
                {
                    "payout_id": r.payout_id,
                    "charge_count": r.count,
                    "total_net": float(r.total_net or 0),
                }
                for r in gwb_payout[:10] if r.payout_id
            ],
        },
    }
