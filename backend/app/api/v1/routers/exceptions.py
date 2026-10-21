"""Exception investigation and review endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import (
    AIInvestigation, AuditEvent, ExceptionReview, ReconciliationException, ReviewStatus
)
from app.api.v1.routers.reconciliation import _format_exception

router = APIRouter()


class ReviewRequest(BaseModel):
    action: str  # "open", "in_review", "resolved", "dismissed"
    reviewer: str = "system"
    notes: str = ""


@router.get("/exceptions")
def list_exceptions(
    category: str = Query(None),
    gateway: str = Query(None),
    review_status: str = Query(None),
    currency: str = Query(None),
    severity: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(ReconciliationException)
    if category:
        q = q.filter(ReconciliationException.category == category)
    if gateway:
        q = q.filter(ReconciliationException.gateway == gateway)
    if review_status:
        q = q.filter(ReconciliationException.review_status == review_status)
    if currency:
        q = q.filter(ReconciliationException.currency == currency)
    if severity:
        q = q.filter(ReconciliationException.severity == severity)
    total = q.count()
    items = q.order_by(ReconciliationException.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_format_exception(e) for e in items],
    }


@router.get("/exceptions/{exception_id}")
def get_exception(exception_id: str, db: Session = Depends(get_db)):
    exc = db.query(ReconciliationException).filter_by(id=exception_id).first()
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found")
    investigations = db.query(AIInvestigation).filter_by(exception_id=exception_id).order_by(AIInvestigation.created_at.desc()).all()
    reviews = db.query(ExceptionReview).filter_by(exception_id=exception_id).order_by(ExceptionReview.created_at.asc()).all()
    
    result = _format_exception(exc)
    result["evidence"] = exc.evidence
    result["investigations"] = [
        {
            "id": inv.id,
            "provider": inv.provider,
            "model": inv.model,
            "is_ai_generated": inv.is_ai_generated,
            "summary": inv.summary,
            "verified_facts": inv.verified_facts,
            "possible_explanations": inv.possible_explanations,
            "missing_information": inv.missing_information,
            "recommended_steps": inv.recommended_steps,
            "confidence_assessment": inv.confidence_assessment,
            "status": inv.status,
            "created_at": inv.created_at.isoformat(),
        }
        for inv in investigations
    ]
    result["review_history"] = [
        {
            "id": r.id,
            "reviewer": r.reviewer,
            "action": r.action,
            "previous_status": r.previous_status,
            "new_status": r.new_status,
            "notes": r.notes,
            "created_at": r.created_at.isoformat(),
        }
        for r in reviews
    ]
    return result


@router.post("/exceptions/{exception_id}/investigate")
async def investigate(exception_id: str, db: Session = Depends(get_db)):
    """Trigger AI (or deterministic fallback) investigation."""
    exc = db.query(ReconciliationException).filter_by(id=exception_id).first()
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found")

    from app.services.ai.investigator import investigate_exception

    exc_data = {
        "id": exc.id,
        "category": exc.category,
        "gateway": exc.gateway,
        "currency": exc.currency,
        "description": exc.description,
        "amount_at_stake": exc.amount_at_stake,
        "amount_difference": exc.amount_difference,
        "expected_value": exc.expected_value,
        "observed_value": exc.observed_value,
        "evidence": exc.evidence,
        "source_payment_id": exc.source_payment_id,
        "source_txn_id": exc.source_txn_id,
        "source_refund_id": exc.source_refund_id,
    }

    result = await investigate_exception(exc_data)

    investigation = AIInvestigation(
        id=result["id"],
        exception_id=exception_id,
        provider=result["provider"],
        model=result["model"],
        prompt_version=result["prompt_version"],
        is_ai_generated=result["is_ai_generated"],
        evidence_fingerprint=result.get("evidence_fingerprint"),
        summary=result.get("summary"),
        verified_facts=result.get("verified_facts"),
        possible_explanations=result.get("possible_explanations"),
        missing_information=result.get("missing_information"),
        recommended_steps=result.get("recommended_steps"),
        confidence_assessment=result.get("confidence_assessment"),
        status=result.get("status", "completed"),
        error_message=result.get("error_message"),
    )
    db.add(investigation)

    # Audit
    db.add(AuditEvent(
        id=str(uuid.uuid4()),
        event_type="exception_investigated",
        entity_type="reconciliation_exception",
        entity_id=exception_id,
        actor="system",
        payload={"investigation_id": investigation.id, "is_ai": result["is_ai_generated"]},
    ))
    db.commit()

    return {
        "investigation_id": investigation.id,
        "is_ai_generated": investigation.is_ai_generated,
        "summary": investigation.summary,
        "status": investigation.status,
    }


@router.patch("/exceptions/{exception_id}/review")
def review_exception(
    exception_id: str,
    body: ReviewRequest,
    db: Session = Depends(get_db),
):
    exc = db.query(ReconciliationException).filter_by(id=exception_id).first()
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found")

    valid_actions = {ReviewStatus.OPEN, ReviewStatus.IN_REVIEW, ReviewStatus.RESOLVED, ReviewStatus.DISMISSED}
    if body.action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action. Must be one of: {valid_actions}")

    previous = exc.review_status
    exc.review_status = body.action

    review = ExceptionReview(
        id=str(uuid.uuid4()),
        exception_id=exception_id,
        reviewer=body.reviewer,
        action=body.action,
        previous_status=previous,
        new_status=body.action,
        notes=body.notes,
    )
    db.add(review)

    db.add(AuditEvent(
        id=str(uuid.uuid4()),
        event_type="exception_reviewed",
        entity_type="reconciliation_exception",
        entity_id=exception_id,
        actor=body.reviewer,
        payload={"previous_status": previous, "new_status": body.action, "notes": body.notes[:200]},
    ))
    db.commit()
    return {"status": "updated", "new_review_status": exc.review_status}


@router.get("/exceptions/{exception_id}/audit")
def get_audit_trail(exception_id: str, db: Session = Depends(get_db)):
    events = (
        db.query(AuditEvent)
        .filter_by(entity_type="reconciliation_exception", entity_id=exception_id)
        .order_by(AuditEvent.created_at.asc())
        .all()
    )
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "actor": e.actor,
            "payload": e.payload,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]
