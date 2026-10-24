"""Analytics and gateway cost endpoints."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.analytics_service import get_gateway_cost_analysis, get_overview_stats, get_settlement_analysis

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
    return get_settlement_analysis(db)
