"""Pricing rules and savings scenario endpoints."""
from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import PricingRule, SavingsScenario

router = APIRouter()


class PricingRuleCreate(BaseModel):
    gateway: str
    rule_name: str
    payment_method: Optional[str] = None
    currency: Optional[str] = None
    country: Optional[str] = None
    is_international: Optional[bool] = None
    fee_rate_pct: Optional[float] = None
    fixed_fee: Optional[float] = None
    fixed_fee_currency: Optional[str] = None
    tax_on_fee_pct: Optional[float] = None
    min_fee: Optional[float] = None
    max_fee: Optional[float] = None
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    notes: Optional[str] = None
    is_illustrative: bool = True


class SavingsScenarioCreate(BaseModel):
    name: str
    current_gateway: str
    alternative_gateway: str
    currency: str
    payment_method: Optional[str] = None
    country: Optional[str] = None
    eligible_volume: float
    current_pricing_rule_id: Optional[str] = None
    alternative_pricing_rule_id: Optional[str] = None


@router.get("/pricing-rules")
def list_pricing_rules(db: Session = Depends(get_db)):
    rules = db.query(PricingRule).order_by(PricingRule.created_at.desc()).all()
    return [_format_rule(r) for r in rules]


@router.post("/pricing-rules")
def create_pricing_rule(body: PricingRuleCreate, db: Session = Depends(get_db)):
    rule = PricingRule(
        id=str(uuid.uuid4()),
        gateway=body.gateway,
        rule_name=body.rule_name,
        payment_method=body.payment_method,
        currency=body.currency,
        country=body.country,
        is_international=body.is_international,
        fee_rate_pct=Decimal(str(body.fee_rate_pct)) if body.fee_rate_pct is not None else None,
        fixed_fee=Decimal(str(body.fixed_fee)) if body.fixed_fee is not None else None,
        fixed_fee_currency=body.fixed_fee_currency,
        tax_on_fee_pct=Decimal(str(body.tax_on_fee_pct)) if body.tax_on_fee_pct is not None else None,
        min_fee=Decimal(str(body.min_fee)) if body.min_fee is not None else None,
        max_fee=Decimal(str(body.max_fee)) if body.max_fee is not None else None,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        notes=body.notes,
        is_illustrative=body.is_illustrative,
    )
    db.add(rule)
    db.commit()
    return _format_rule(rule)


@router.patch("/pricing-rules/{rule_id}")
def update_pricing_rule(rule_id: str, body: PricingRuleCreate, db: Session = Depends(get_db)):
    rule = db.query(PricingRule).filter_by(id=rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Pricing rule not found")
    for field, val in body.model_dump(exclude_none=True).items():
        if hasattr(rule, field):
            setattr(rule, field, val)
    db.commit()
    return _format_rule(rule)


@router.post("/savings-scenarios")
def create_savings_scenario(body: SavingsScenarioCreate, db: Session = Depends(get_db)):
    """
    Compute estimated savings of routing volume from current to alternative gateway.
    Uses configured pricing rules. Result is clearly labeled as an estimate.
    """
    current_rule = None
    alt_rule = None

    if body.current_pricing_rule_id:
        current_rule = db.query(PricingRule).filter_by(id=body.current_pricing_rule_id).first()
    if body.alternative_pricing_rule_id:
        alt_rule = db.query(PricingRule).filter_by(id=body.alternative_pricing_rule_id).first()

    volume = Decimal(str(body.eligible_volume))
    limitations = []
    scenario_time = datetime.now(timezone.utc)

    def matches(rule: Optional[PricingRule], gateway_name: str, label: str) -> bool:
        if rule is None:
            limitations.append(f"No {label} gateway pricing rule selected — fee is not estimated.")
            return False
        eligible = True
        if rule.gateway != gateway_name:
            limitations.append(f"{label.title()} rule gateway does not match the selected gateway.")
            eligible = False
        if rule.currency and rule.currency != body.currency:
            limitations.append(f"{label.title()} rule currency {rule.currency} does not match scenario currency {body.currency}.")
            eligible = False
        if rule.payment_method and rule.payment_method != body.payment_method:
            limitations.append(f"{label.title()} rule payment method does not match the scenario.")
            eligible = False
        if rule.country and rule.country != body.country:
            limitations.append(f"{label.title()} rule country does not match the scenario.")
            eligible = False
        if rule.fixed_fee is not None and rule.fixed_fee_currency and rule.fixed_fee_currency != body.currency:
            limitations.append(f"{label.title()} fixed fee currency does not match scenario currency.")
            eligible = False
        if rule.effective_from and rule.effective_from.date() > scenario_time.date():
            limitations.append(f"{label.title()} pricing rule is not yet effective.")
            eligible = False
        if rule.effective_to and rule.effective_to.date() < scenario_time.date():
            limitations.append(f"{label.title()} pricing rule has expired.")
            eligible = False
        return eligible

    current_fee = _estimate_fee(volume, current_rule) if matches(current_rule, body.current_gateway, "current") else None
    alt_fee = _estimate_fee(volume, alt_rule) if matches(alt_rule, body.alternative_gateway, "alternative") else None
    difference = current_fee - alt_fee if (current_fee is not None and alt_fee is not None) else None

    if current_rule and current_rule.is_illustrative:
        limitations.append("Current pricing rule is illustrative — not a verified contract rate.")
    elif current_rule:
        limitations.append("Current pricing input is not independently verified against a signed contract.")
    if alt_rule and alt_rule.is_illustrative:
        limitations.append("Alternative pricing rule is illustrative — not a verified contract rate.")
    elif alt_rule:
        limitations.append("Alternative pricing input is not independently verified against a signed contract.")

    scenario = SavingsScenario(
        id=str(uuid.uuid4()),
        name=body.name,
        current_gateway=body.current_gateway,
        alternative_gateway=body.alternative_gateway,
        currency=body.currency,
        payment_method=body.payment_method,
        country=body.country,
        eligible_volume=volume,
        current_pricing_rule_id=body.current_pricing_rule_id,
        alternative_pricing_rule_id=body.alternative_pricing_rule_id,
        current_estimated_fee=current_fee,
        alternative_estimated_fee=alt_fee,
        estimated_difference=difference,
        assumptions={
            "volume_currency": body.currency,
            "current_rule": _format_rule(current_rule) if current_rule else None,
            "alternative_rule": _format_rule(alt_rule) if alt_rule else None,
        },
        limitations="\n".join(limitations) if limitations else None,
        is_estimate=True,
    )
    db.add(scenario)
    db.commit()

    return {
        "scenario_id": scenario.id,
        "name": scenario.name,
        "eligible_volume": str(volume),
        "currency": body.currency,
        "current_estimated_fee": str(current_fee) if current_fee is not None else None,
        "alternative_estimated_fee": str(alt_fee) if alt_fee is not None else None,
        "estimated_difference": str(difference) if difference is not None else None,
        "is_estimate": True,
        "limitations": limitations,
        "assumptions_note": (
            "This is a scenario estimate based on configured pricing rules. "
            "Actual fees depend on gateway contract terms, FX rates, and transaction mix. "
            "Do not treat this as guaranteed savings."
        ),
    }


@router.get("/savings-scenarios/{scenario_id}")
def get_savings_scenario(scenario_id: str, db: Session = Depends(get_db)):
    s = db.query(SavingsScenario).filter_by(id=scenario_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return {
        "id": s.id,
        "name": s.name,
        "current_gateway": s.current_gateway,
        "alternative_gateway": s.alternative_gateway,
        "currency": s.currency,
        "eligible_volume": str(s.eligible_volume) if s.eligible_volume else None,
        "current_estimated_fee": str(s.current_estimated_fee) if s.current_estimated_fee else None,
        "alternative_estimated_fee": str(s.alternative_estimated_fee) if s.alternative_estimated_fee else None,
        "estimated_difference": str(s.estimated_difference) if s.estimated_difference else None,
        "limitations": s.limitations,
        "is_estimate": s.is_estimate,
        "created_at": s.created_at.isoformat(),
    }


def _estimate_fee(volume: Decimal, rule: Optional[PricingRule]) -> Optional[Decimal]:
    if rule is None or rule.fee_rate_pct is None:
        return None
    pct_fee = volume * rule.fee_rate_pct / Decimal("100")
    if rule.fixed_fee:
        pct_fee += rule.fixed_fee
    if rule.min_fee and pct_fee < rule.min_fee:
        pct_fee = rule.min_fee
    if rule.max_fee and pct_fee > rule.max_fee:
        pct_fee = rule.max_fee
    # Tax on fee
    if rule.tax_on_fee_pct:
        pct_fee += pct_fee * rule.tax_on_fee_pct / Decimal("100")
    return pct_fee.quantize(Decimal("0.01"))


def _format_rule(rule: Optional[PricingRule]) -> Optional[dict]:
    if rule is None:
        return None
    return {
        "id": rule.id,
        "gateway": rule.gateway,
        "rule_name": rule.rule_name,
        "payment_method": rule.payment_method,
        "currency": rule.currency,
        "country": rule.country,
        "fee_rate_pct": str(rule.fee_rate_pct) if rule.fee_rate_pct else None,
        "fixed_fee": str(rule.fixed_fee) if rule.fixed_fee else None,
        "tax_on_fee_pct": str(rule.tax_on_fee_pct) if rule.tax_on_fee_pct else None,
        "is_illustrative": rule.is_illustrative,
        "evidence_status": "illustrative" if rule.is_illustrative else "unverified_input",
        "notes": rule.notes,
        "created_at": rule.created_at.isoformat(),
        "effective_from": rule.effective_from.isoformat() if rule.effective_from else None,
        "effective_to": rule.effective_to.isoformat() if rule.effective_to else None,
    }
