"""Reconciliation endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import (
    ReconciliationException, ReconciliationMatch, ReconciliationRun, ReconciliationStatus
)
from app.services.reconciliation.engine import run_reconciliation

router = APIRouter()


@router.post("/reconciliation/runs")
def create_reconciliation_run(db: Session = Depends(get_db)):
    """Trigger a new reconciliation run."""
    run = ReconciliationRun(
        id=str(uuid.uuid4()),
        status=ReconciliationStatus.PENDING,
        rule_version="1.0",
    )
    db.add(run)
    db.commit()

    # Run synchronously (Celery optional)
    try:
        from app.workers.tasks import run_reconciliation_task
        run_reconciliation_task.delay(run.id)
    except Exception:
        try:
            run_reconciliation(db, run.id)
            db.commit()
        except Exception as exc:
            run.status = ReconciliationStatus.FAILED
            run.error_message = str(exc)[:1000]
            db.commit()

    db.refresh(run)
    return {
        "run_id": run.id,
        "status": run.status,
        "message": "Reconciliation run initiated",
    }


@router.get("/reconciliation/runs")
def list_runs(db: Session = Depends(get_db)):
    runs = db.query(ReconciliationRun).order_by(ReconciliationRun.created_at.desc()).limit(20).all()
    return [_format_run(r) for r in runs]


@router.get("/reconciliation/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(ReconciliationRun).filter_by(id=run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _format_run(run)


@router.get("/reconciliation/runs/{run_id}/matches")
def get_matches(
    run_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(ReconciliationMatch).filter_by(run_id=run_id)
    total = q.count()
    matches = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": m.id,
                "match_method": m.match_method,
                "confidence": m.confidence,
                "payment_id": m.payment_id,
                "gateway_txn_id": m.gateway_txn_id,
                "amount_difference": str(m.amount_difference) if m.amount_difference else None,
                "currency": m.currency,
            }
            for m in matches
        ],
    }


@router.get("/reconciliation/runs/{run_id}/exceptions")
def get_run_exceptions(
    run_id: str,
    category: str = Query(None),
    severity: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(ReconciliationException).filter_by(run_id=run_id)
    if category:
        q = q.filter(ReconciliationException.category == category)
    if severity:
        q = q.filter(ReconciliationException.severity == severity)
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_format_exception(e) for e in items],
    }


def _format_run(run: ReconciliationRun) -> dict:
    return {
        "id": run.id,
        "status": run.status,
        "rule_version": run.rule_version,
        "total_records": run.total_records,
        "matched_records": run.matched_records,
        "unmatched_records": run.unmatched_records,
        "exception_count": run.exception_count,
        "summary": run.summary,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat(),
    }


def _format_exception(e: ReconciliationException) -> dict:
    return {
        "id": e.id,
        "run_id": e.run_id,
        "category": e.category,
        "severity": e.severity,
        "gateway": e.gateway,
        "currency": e.currency,
        "amount_at_stake": str(e.amount_at_stake) if e.amount_at_stake else None,
        "amount_difference": str(e.amount_difference) if e.amount_difference else None,
        "expected_value": str(e.expected_value) if e.expected_value else None,
        "observed_value": str(e.observed_value) if e.observed_value else None,
        "description": e.description,
        "review_status": e.review_status,
        "source_payment_id": e.source_payment_id,
        "source_txn_id": e.source_txn_id,
        "created_at": e.created_at.isoformat(),
    }
