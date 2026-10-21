"""Import job status and retry endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import ImportJob, ImportRowError

router = APIRouter()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(ImportJob).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    errors = db.query(ImportRowError).filter_by(job_id=job_id).limit(200).all()
    return {
        "id": job.id,
        "dataset_id": job.dataset_id,
        "status": job.status,
        "total_rows": job.total_rows,
        "processed_rows": job.processed_rows,
        "imported_rows": job.imported_rows,
        "skipped_rows": job.skipped_rows,
        "duplicate_count": job.duplicate_count,
        "warning_count": job.warning_count,
        "error_count": job.error_count,
        "error_message": job.error_message,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "row_errors": [
            {
                "row_number": e.row_number,
                "severity": e.severity,
                "field": e.field_name,
                "message": e.message,
                "raw_value": e.raw_value,
            }
            for e in errors
        ],
    }


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(ImportJob).filter_by(id=job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("failed", "queued"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry job in status '{job.status}'. Only failed or queued jobs can be retried.",
        )

    # Create a fresh job for the same dataset
    from app.services.import_service import create_import_job
    new_job = create_import_job(db, job.dataset_id)
    db.commit()

    # Trigger import
    try:
        from app.workers.tasks import run_import_task
        run_import_task.delay(new_job.id)
    except Exception:
        from app.services.import_service import run_import_job
        run_import_job(db, new_job.id)
        db.commit()

    return {"new_job_id": new_job.id, "message": "Retry job created and queued"}
