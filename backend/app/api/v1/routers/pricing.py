"""Pricing rules and savings scenario endpoints."""
from __future__ import annotations

import uuid
import re
from decimal import Decimal
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import PricingRule, SavingsScenario

router = APIRouter()


class PricingRuleCreate(BaseModel):
    gateway: Literal["gateway_a", "gateway_b"]
    rule_name: str = Field(min_length=1, max_length=255)
    payment_method: Optional[str] = Field(default=None, max_length=50)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=10)
    country: Optional[str] = None
    is_international: Optional[bool] = None
    fee_rate_pct: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    fixed_fee: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    fixed_fee_currency: Optional[str] = Field(default=None, max_length=10)
    tax_on_fee_pct: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    min_fee: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    max_fee: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    notes: Optional[str] = None
    is_illustrative: bool = True

    @field_validator("rule_name")
    @classmethod
    def rule_name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Rule name cannot be blank")
        return value

    @field_validator("currency", "fixed_fee_currency")
    @classmethod
    def validate_currency_code_format(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("Currency must be a three-letter code, such as INR or USD")
        return value

    @field_validator("country")
    @classmethod
    def validate_country_code_format(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", value):
            raise ValueError("Country must be a two-letter code, such as IN or US")
        return value

    @field_validator("payment_method")
    @classmethod
    def normalize_payment_method(cls, value: Optional[str]) -> Optional[str]:
        normalized = value.strip().lower() if value is not None else None
        return normalized or None

    @model_validator(mode="after")
    def fee_bounds_must_be_ordered(self):
        if self.min_fee is not None and self.max_fee is not None and self.min_fee > self.max_fee:
            raise ValueError("Minimum fee cannot exceed maximum fee")
        if self.effective_from and self.effective_to:
            start = self.effective_from if self.effective_from.tzinfo else self.effective_from.replace(tzinfo=timezone.utc)
            end = self.effective_to if self.effective_to.tzinfo else self.effective_to.replace(tzinfo=timezone.utc)
            if start > end:
                raise ValueError("Effective start must be on or before effective end")
        return self


class SavingsScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    current_gateway: Literal["gateway_a", "gateway_b"]
    alternative_gateway: Literal["gateway_a", "gateway_b"]
    currency: str = Field(min_length=3, max_length=10)
    payment_method: Optional[str] = None
    country: Optional[str] = None
    eligible_volume: float = Field(ge=0, allow_inf_nan=False)
    current_pricing_rule_id: str = Field(min_length=1)
    alternative_pricing_rule_id: str = Field(min_length=1)

    @field_validator("name", "currency")
    @classmethod
    def scenario_required_values_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value

    @field_validator("current_pricing_rule_id", "alternative_pricing_rule_id")
    @classmethod
    def normalize_rule_ids(cls, value: str) -> str:
        return value.strip()

    @field_validator("currency")
    @classmethod
    def validate_scenario_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("Currency must be a three-letter code, such as INR or USD")
        return value

    @field_validator("country")
    @classmethod
    def validate_scenario_country(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", value):
            raise ValueError("Country must be a two-letter code, such as IN or US")
        return value

    @field_validator("payment_method")
    @classmethod
    def normalize_scenario_payment_method(cls, value: Optional[str]) -> Optional[str]:
        normalized = value.strip().lower() if value is not None else None
        return normalized or None

    @model_validator(mode="after")
    def gateways_must_differ(self):
        if self.current_gateway == self.alternative_gateway:
            raise ValueError("Current and alternative gateways must be different")
        if self.current_pricing_rule_id == self.alternative_pricing_rule_id:
            raise ValueError("Current and alternative pricing rules must be different")
        return self


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
    # PATCH must distinguish an omitted field (preserve it) from explicit null (clear it).
    for field, val in body.model_dump(exclude_unset=True).items():
        if hasattr(rule, field):
            setattr(rule, field, val)
    db.commit()
    return _format_rule(rule)


@router.delete("/pricing-rules/{rule_id}")
def delete_pricing_rule(rule_id: str, db: Session = Depends(get_db)):
    rule = db.query(PricingRule).filter_by(id=rule_id).first()
    if rule is None:
        raise HTTPException(status_code=404, detail="Pricing rule not found")
    referenced = db.query(SavingsScenario.id).filter(
        or_(
            SavingsScenario.current_pricing_rule_id == rule_id,
            SavingsScenario.alternative_pricing_rule_id == rule_id,
        )
    ).first()
    if referenced:
        raise HTTPException(
            status_code=409,
            detail="This rule is referenced by a saved savings scenario and cannot be deleted.",
        )
    db.delete(rule)
    db.commit()
    return {"deleted": True, "id": rule_id}


@router.post("/savings-scenarios")
def create_savings_scenario(body: SavingsScenarioCreate, db: Session = Depends(get_db)):
    """
    Compute estimated savings of routing volume from current to alternative gateway.
    Uses configured pricing rules. Result is clearly labeled as an estimate.
    """
    current_rule = db.query(PricingRule).filter_by(id=body.current_pricing_rule_id).first()
    if current_rule is None:
        raise HTTPException(status_code=404, detail="Current pricing rule not found")
    alt_rule = db.query(PricingRule).filter_by(id=body.alternative_pricing_rule_id).first()
    if alt_rule is None:
        raise HTTPException(status_code=404, detail="Alternative pricing rule not found")

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
        if rule.currency and rule.currency.upper() != body.currency.upper():
            limitations.append(f"{label.title()} rule currency {rule.currency} does not match scenario currency {body.currency}.")
            eligible = False
        elif not rule.currency:
            limitations.append(f"{label.title()} rule has no currency scope; scenario currency {body.currency} is assumed.")
        if rule.payment_method and rule.payment_method.strip().lower() != (body.payment_method or "").strip().lower():
            limitations.append(f"{label.title()} rule payment method does not match the scenario.")
            eligible = False
        elif body.payment_method and not rule.payment_method:
            limitations.append(f"{label.title()} rule has no payment-method scope; generic applicability is assumed.")
        if rule.country and rule.country.upper() != (body.country or "").upper():
            limitations.append(f"{label.title()} rule country does not match the scenario.")
            eligible = False
        elif body.country and not rule.country:
            limitations.append(f"{label.title()} rule has no geography scope; generic applicability is assumed.")
        if rule.fee_rate_pct is None:
            limitations.append(f"{label.title()} rule has no percentage fee rate; fee estimate is unavailable.")
            eligible = False
        if rule.fixed_fee is not None and rule.fixed_fee_currency and rule.fixed_fee_currency.upper() != body.currency.upper():
            limitations.append(f"{label.title()} fixed fee currency does not match scenario currency.")
            eligible = False
        elif rule.fixed_fee is not None and not rule.fixed_fee_currency:
            limitations.append(f"{label.title()} fixed-fee currency is missing; scenario currency is assumed.")
        if rule.effective_from and rule.effective_from.date() > scenario_time.date():
            limitations.append(f"{label.title()} pricing rule is not yet effective.")
            eligible = False
        if rule.effective_to and rule.effective_to.date() < scenario_time.date():
            limitations.append(f"{label.title()} pricing rule has expired.")
            eligible = False
        return eligible

    current_eligible = matches(current_rule, body.current_gateway, "current")
    alternative_eligible = matches(alt_rule, body.alternative_gateway, "alternative")
    if not current_eligible or not alternative_eligible:
        raise HTTPException(status_code=422, detail={
            "message": "Select two compatible rules with configured percentage fee rates.",
            "issues": limitations,
        })

    current_fee = _estimate_fee(volume, current_rule)
    alt_fee = _estimate_fee(volume, alt_rule)
    difference = current_fee - alt_fee

    if current_rule and current_rule.is_illustrative:
        limitations.append("Current pricing rule is illustrative — not a verified contract rate.")
    elif current_rule:
        limitations.append("Current pricing input is not independently verified against a signed contract.")
    if alt_rule and alt_rule.is_illustrative:
        limitations.append("Alternative pricing rule is illustrative — not a verified contract rate.")
    elif alt_rule:
        limitations.append("Alternative pricing input is not independently verified against a signed contract.")

    if not body.country:
        limitations.append("Country/geography was not specified; no geography-specific routing conclusion is available.")
    if not body.payment_method:
        limitations.append("Payment method was not specified; no method-specific routing conclusion is available.")
    fixed_fee_basis = "once_per_scenario"
    if current_rule.fixed_fee is not None or alt_rule.fixed_fee is not None:
        limitations.append("Each configured fixed fee is applied once to the full scenario, not per transaction; transaction count is not modeled.")

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
            "fixed_fee_basis": fixed_fee_basis,
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
        "fixed_fee_basis": fixed_fee_basis,
        "currency": body.currency,
        "current_estimated_fee": str(current_fee) if current_fee is not None else None,
        "alternative_estimated_fee": str(alt_fee) if alt_fee is not None else None,
        "estimated_difference": str(difference) if difference is not None else None,
        "estimated_difference_pct": _difference_pct(current_fee, difference),
        "estimated_lower_cost_gateway": (
            body.current_gateway if difference is not None and difference < 0
            else body.alternative_gateway if difference is not None and difference > 0
            else None
        ),
        "recommendation_status": "estimate_only_unverified_rates" if difference is not None else "unavailable",
        "reliable_recommendation": False,
        "is_estimate": True,
        "limitations": limitations,
        "assumptions_note": (
            "This is a scenario estimate based on configured pricing rules. "
            "The percentage fee applies to the entered eligible payment value; any configured fixed fee is added once per scenario, not per transaction. "
            "Per-transaction fixed-fee units, FX, actual transaction mix, and signed contract terms are not independently verified. "
            "A lower estimated fee is not a reliable routing recommendation or guaranteed savings."
        ),
    }


@router.get("/savings-scenarios")
def list_savings_scenarios(db: Session = Depends(get_db)):
    scenarios = db.query(SavingsScenario).order_by(SavingsScenario.created_at.desc()).limit(100).all()
    return [_format_scenario(scenario) for scenario in scenarios]


@router.get("/savings-scenarios/{scenario_id}")
def get_savings_scenario(scenario_id: str, db: Session = Depends(get_db)):
    s = db.query(SavingsScenario).filter_by(id=scenario_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Scenario not found")
    formatted = _format_scenario(s)
    # Preserve the existing detail endpoint's newline-delimited limitations field.
    formatted["limitations"] = s.limitations
    return formatted


def _format_scenario(s: SavingsScenario) -> dict:
    difference_pct = _difference_pct(s.current_estimated_fee, s.estimated_difference)
    limitations = [item for item in (s.limitations or "").splitlines() if item]
    return {
        "id": s.id,
        "scenario_id": s.id,
        "name": s.name,
        "current_gateway": s.current_gateway,
        "alternative_gateway": s.alternative_gateway,
        "currency": s.currency,
        "payment_method": s.payment_method,
        "country": s.country,
        "eligible_volume": str(s.eligible_volume) if s.eligible_volume is not None else None,
        "current_estimated_fee": str(s.current_estimated_fee) if s.current_estimated_fee is not None else None,
        "alternative_estimated_fee": str(s.alternative_estimated_fee) if s.alternative_estimated_fee is not None else None,
        "estimated_difference": str(s.estimated_difference) if s.estimated_difference is not None else None,
        "estimated_difference_pct": difference_pct,
        "estimated_lower_cost_gateway": (
            s.current_gateway if s.estimated_difference is not None and s.estimated_difference < 0
            else s.alternative_gateway if s.estimated_difference is not None and s.estimated_difference > 0
            else None
        ),
        "current_pricing_rule_id": s.current_pricing_rule_id,
        "alternative_pricing_rule_id": s.alternative_pricing_rule_id,
        "fixed_fee_basis": (s.assumptions or {}).get("fixed_fee_basis", "once_per_scenario"),
        "limitations": limitations,
        "is_estimate": s.is_estimate,
        "created_at": s.created_at.isoformat(),
    }


def _estimate_fee(volume: Decimal, rule: Optional[PricingRule]) -> Optional[Decimal]:
    if rule is None or rule.fee_rate_pct is None:
        return None
    pct_fee = volume * rule.fee_rate_pct / Decimal("100")
    if rule.fixed_fee is not None:
        pct_fee += rule.fixed_fee
    if rule.min_fee is not None and pct_fee < rule.min_fee:
        pct_fee = rule.min_fee
    if rule.max_fee is not None and pct_fee > rule.max_fee:
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
        "fixed_fee_currency": rule.fixed_fee_currency,
        "country": rule.country,
        "fee_rate_pct": str(rule.fee_rate_pct) if rule.fee_rate_pct is not None else None,
        "fixed_fee": str(rule.fixed_fee) if rule.fixed_fee is not None else None,
        "tax_on_fee_pct": str(rule.tax_on_fee_pct) if rule.tax_on_fee_pct is not None else None,
        "min_fee": str(rule.min_fee) if rule.min_fee is not None else None,
        "max_fee": str(rule.max_fee) if rule.max_fee is not None else None,
        "is_international": rule.is_international,
        "is_illustrative": rule.is_illustrative,
        "evidence_status": "illustrative" if rule.is_illustrative else "unverified_input",
        "notes": rule.notes,
        "created_at": rule.created_at.isoformat(),
        "effective_from": rule.effective_from.isoformat() if rule.effective_from else None,
        "effective_to": rule.effective_to.isoformat() if rule.effective_to else None,
    }


def _difference_pct(current_fee: Optional[Decimal], difference: Optional[Decimal]) -> Optional[str]:
    if current_fee is None or difference is None or current_fee <= 0:
        return None
    return str((difference / current_fee * Decimal("100")).quantize(Decimal("0.01")))
