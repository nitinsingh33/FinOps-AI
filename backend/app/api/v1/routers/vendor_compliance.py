"""API for vendor GST, TDS, MSME and master-data compliance workflows."""
from __future__ import annotations

from datetime import date
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.vendor_compliance import (
    RuleApprovalStatus, TaxRule, VendorComplianceException, VendorMaster,
    VendorMasterCleanupItem, VendorScorecard,
)
from app.services.vendor_compliance.compliance_engine import run_vendor_compliance_checks
from app.services.vendor_compliance.synthetic_data import seed_vendor_compliance_data
from app.services.vendor_compliance.gst_checks import validate_gstin_format, validate_pan_format, check_pan_gstin_consistency
from app.services.vendor_compliance.msme_checks import validate_msme_udyam_format

router = APIRouter(prefix="/vendor-compliance", tags=["Vendor Compliance"])


def _vendor(v: VendorMaster, scorecard: Optional[VendorScorecard] = None) -> dict:
    return {
        "id": v.id, "vendor_code": v.vendor_code, "legal_name": v.legal_name,
        "trade_name": v.trade_name, "pan": v.pan, "gstin": v.gstin,
        "vendor_type": v.vendor_type, "msme_type": v.msme_type,
        "is_synthetic": v.is_synthetic,
        "scorecard": _scorecard(scorecard) if scorecard else None,
    }


def _scorecard(s: VendorScorecard) -> dict:
    return {
        "id": s.id, "vendor_id": s.vendor_id, "status": s.status,
        "risk_score": s.risk_score, "gst_status": s.gst_status,
        "tds_status": s.tds_status, "msme_status": s.msme_status,
        "master_data_status": s.master_data_status,
        "total_amount_at_stake": str(s.total_amount_at_stake), "currency": s.currency,
        "summary_reasons": s.summary_reasons or [], "evidence_coverage": s.evidence_coverage or {},
        "recommended_actions": s.recommended_actions or [],
        "last_assessed_at": s.last_assessed_at.isoformat() if s.last_assessed_at else None,
    }


@router.post("/seed")
def seed_synthetic_data(db: Session = Depends(get_db)):
    counts = seed_vendor_compliance_data(db)
    return {"created": counts, "synthetic": True, "notice": "Synthetic data is for demonstration only."}


@router.get("/vendors")
def list_vendors(q: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(VendorMaster)
    if q:
        term = f"%{q}%"
        query = query.filter(or_(VendorMaster.vendor_code.ilike(term), VendorMaster.legal_name.ilike(term)))
    vendors = query.order_by(VendorMaster.vendor_code).all()
    scorecards = {s.vendor_id: s for s in db.query(VendorScorecard).all()}
    return [_vendor(v, scorecards.get(v.id)) for v in vendors]


@router.post("/checks/run")
def run_checks(vendor_id: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(VendorMaster)
    if vendor_id:
        query = query.filter_by(id=vendor_id)
    vendors = query.order_by(VendorMaster.vendor_code).all()
    if vendor_id and not vendors:
        raise HTTPException(status_code=404, detail="Vendor not found")
    scorecards = [run_vendor_compliance_checks(db, v.id) for v in vendors]
    db.commit()
    return {"assessed": len(scorecards), "scorecards": [_scorecard(s) for s in scorecards]}


@router.get("/scorecards")
def list_scorecards(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(VendorScorecard)
    if status:
        query = query.filter_by(status=status)
    return [_scorecard(s) for s in query.order_by(VendorScorecard.risk_score.desc()).all()]


@router.get("/exceptions")
def list_exceptions(category: Optional[str] = None, status: Optional[str] = None,
                    vendor_id: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(VendorComplianceException)
    if category: query = query.filter_by(category=category)
    if status: query = query.filter_by(review_status=status)
    if vendor_id: query = query.filter_by(vendor_id=vendor_id)
    rows = query.order_by(VendorComplianceException.created_at.desc()).limit(1000).all()
    return [{"id": e.id, "vendor_id": e.vendor_id, "check_code": e.check_code,
             "category": e.category, "severity": e.severity, "title": e.title,
             "description": e.description, "amount_at_stake": str(e.amount_at_stake) if e.amount_at_stake is not None else None,
             "currency": e.currency, "missing_information": e.missing_information or [],
             "suggested_action": e.suggested_action,
             "review_status": e.review_status, "is_synthetic_warning": e.is_synthetic_warning}
            for e in rows]


@router.post("/master-cleanup/scan")
def scan_vendor_master(db: Session = Depends(get_db)):
    """Create actionable cleanup findings while preserving vendor source values."""
    db.query(VendorMasterCleanupItem).filter_by(status="open").delete(synchronize_session=False)
    findings = []
    vendors = db.query(VendorMaster).all()
    for v in vendors:
        checks = []
        if v.pan and not validate_pan_format(v.pan)[0]:
            checks.append(("invalid_pan", "pan", "PAN format is invalid", "Collect and verify PAN evidence."))
        if v.gstin and not validate_gstin_format(v.gstin)[0]:
            checks.append(("invalid_gstin", "gstin", "GSTIN format is invalid", "Collect GST registration evidence."))
        if v.pan and v.gstin and validate_pan_format(v.pan)[0] and validate_gstin_format(v.gstin)[0] and not check_pan_gstin_consistency(v.pan, v.gstin)[0]:
            checks.append(("pan_gstin_mismatch", "gstin", "PAN does not match the PAN embedded in GSTIN", "Confirm the legal identity with the vendor."))
        if v.msme_type != "non_msme" and not v.udyam_number:
            checks.append(("missing_udyam", "udyam_number", "MSME registration evidence is missing", "Obtain and verify the Udyam certificate."))
        if v.msme_type != "non_msme" and v.udyam_number and not validate_msme_udyam_format(v.udyam_number)[0]:
            checks.append(("invalid_udyam", "udyam_number", "Udyam number format is invalid", "Confirm the Udyam number against source evidence."))
        for issue, field, description, fix in checks:
            item = VendorMasterCleanupItem(id=str(uuid.uuid4()), vendor_id=v.id, issue_type=issue,
                severity="high" if issue in ("invalid_pan", "invalid_gstin", "pan_gstin_mismatch") else "medium",
                field_name=field, description=description, recommended_fix=fix, status="open")
            db.add(item); findings.append(item)
        if v.pan:
            duplicate = db.query(VendorMaster).filter(VendorMaster.id != v.id, VendorMaster.pan == v.pan).order_by(VendorMaster.id).first()
            if duplicate and v.id < duplicate.id:
                item = VendorMasterCleanupItem(id=str(uuid.uuid4()), vendor_id=v.id,
                    duplicate_candidate_vendor_id=duplicate.id, issue_type="duplicate_pan_candidate",
                    severity="medium", field_name="pan",
                    description="Another vendor record has the same PAN. This is a duplicate candidate, not a verified duplicate.",
                    recommended_fix="Review legal entity documents and vendor ownership before merging.", status="open")
                db.add(item); findings.append(item)
    db.commit()
    return [{"id": x.id, "vendor_id": x.vendor_id, "issue_type": x.issue_type,
             "severity": x.severity, "field_name": x.field_name, "description": x.description,
             "recommended_fix": x.recommended_fix, "status": x.status} for x in findings]


@router.get("/master-cleanup")
def list_master_cleanup(status: Optional[str] = "open", db: Session = Depends(get_db)):
    query = db.query(VendorMasterCleanupItem)
    if status: query = query.filter_by(status=status)
    return [{"id": x.id, "vendor_id": x.vendor_id, "issue_type": x.issue_type,
             "severity": x.severity, "field_name": x.field_name, "description": x.description,
             "recommended_fix": x.recommended_fix, "status": x.status}
            for x in query.order_by(VendorMasterCleanupItem.created_at.desc()).all()]


class TaxRuleCreate(BaseModel):
    rule_code: str
    tax_category: str
    description: str
    rate_pct: Decimal
    threshold_amount: Decimal = Decimal("0")
    tax_base: str = "EXCLUDE_GST"
    effective_from: date
    effective_to: Optional[date] = None
    section_1961: Optional[str] = None
    section_2025: Optional[str] = None
    source_reference: Optional[str] = None
    version: str = "1.0"


@router.get("/tax-rules")
def list_tax_rules(db: Session = Depends(get_db)):
    return [{"id": r.id, "rule_code": r.rule_code, "tax_category": r.tax_category,
             "section_1961": r.section_1961, "section_2025": r.section_2025,
             "description": r.description, "rate_pct": str(r.rate_pct),
             "threshold_amount": str(r.threshold_amount), "tax_base": r.tax_base,
             "effective_from": r.effective_from.isoformat(), "effective_to": r.effective_to.isoformat() if r.effective_to else None,
             "verification_status": r.verification_status, "approved_by": r.approved_by,
             "version": r.version, "is_sample_rule": r.is_sample_rule}
            for r in db.query(TaxRule).order_by(TaxRule.rule_code, TaxRule.version).all()]


@router.post("/tax-rules")
def create_tax_rule(body: TaxRuleCreate, db: Session = Depends(get_db)):
    if body.tax_category not in ("gst", "tds"):
        raise HTTPException(status_code=422, detail="tax_category must be gst or tds")
    if not body.source_reference or not body.source_reference.strip():
        raise HTTPException(status_code=422, detail="source_reference is required for review")
    if db.query(TaxRule).filter_by(rule_code=body.rule_code, version=body.version).first():
        raise HTTPException(status_code=409, detail="This rule code and version already exists")
    rule = TaxRule(id=str(uuid.uuid4()), **body.model_dump(), verification_status=RuleApprovalStatus.PENDING_REVIEW,
                   is_sample_rule=False)
    db.add(rule); db.commit(); db.refresh(rule)
    return {"id": rule.id, "rule_code": rule.rule_code, "verification_status": rule.verification_status,
            "version": rule.version, "effective_from": rule.effective_from.isoformat()}


class RuleApproval(BaseModel):
    approved_by: str


@router.post("/tax-rules/{rule_id}/approve")
def approve_tax_rule(rule_id: str, body: RuleApproval, db: Session = Depends(get_db)):
    rule = db.query(TaxRule).filter_by(id=rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Tax rule not found")
    if not body.approved_by.strip():
        raise HTTPException(status_code=422, detail="approved_by is required")
    if rule.is_sample_rule:
        raise HTTPException(status_code=409, detail="Synthetic sample rules cannot be activated. Create a reviewed non-sample version with an authoritative source.")
    rule.verification_status = RuleApprovalStatus.APPROVED
    rule.approved_by = body.approved_by.strip()
    rule.approved_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": rule.id, "rule_code": rule.rule_code, "version": rule.version,
            "verification_status": rule.verification_status, "approved_by": rule.approved_by,
            "approved_at": rule.approved_at.isoformat()}
