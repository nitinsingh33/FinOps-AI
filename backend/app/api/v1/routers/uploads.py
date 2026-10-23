"""Upload endpoints — file upload, registration, and dataset listing."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.models import ImportJob, UploadedDataset
from app.services.import_service import (
    compute_sha256,
    create_import_job,
    register_dataset,
    validate_upload,
)

settings = get_settings()
router = APIRouter()

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

VALID_DATASET_TYPES = ["gwa_payments", "gwa_transactions", "gwa_refunds", "gwb_balance"]


class DatasetResponse(BaseModel):
    id: str
    filename: str
    original_filename: str
    dataset_type: str
    gateway: str
    file_hash_sha256: str
    file_size_bytes: int
    created_at: str

    class Config:
        from_attributes = True


@router.post("/uploads")
async def upload_dataset(
    file: UploadFile = File(...),
    dataset_type: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Upload a gateway Excel file for import.
    Returns dataset_id and triggers a background import job.
    """
    if dataset_type not in VALID_DATASET_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid dataset_type. Must be one of: {VALID_DATASET_TYPES}",
        )

    # Validate
    content = await file.read()
    error = validate_upload(file.filename, file.content_type, len(content))
    if error:
        raise HTTPException(status_code=400, detail=error)

    # Save to disk
    safe_filename = Path(file.filename or "upload.xlsx").name
    unique_name = f"{uuid.uuid4()}_{safe_filename}"
    storage_path = str(UPLOAD_DIR / unique_name)
    with open(storage_path, "wb") as f:
        f.write(content)

    file_hash = compute_sha256(storage_path)

    # Register (idempotent)
    try:
        dataset, is_new = register_dataset(
            db,
            original_filename=file.filename,
            dataset_type=dataset_type,
            storage_path=storage_path,
            file_size=len(content),
            file_hash=file_hash,
            mime_type=file.content_type,
        )
        db.commit()
    except Exception as exc:
        Path(storage_path).unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(exc))

    if not is_new:
        # Already registered — clean up duplicate file
        Path(storage_path).unlink(missing_ok=True)

    # Create import job
    job = create_import_job(db, dataset.id)
    db.commit()

    # Trigger background import (sync fallback if Celery not available)
    import_error = None
    try:
        from app.workers.tasks import run_import_task
        run_import_task.delay(job.id)
    except Exception as queue_exc:
        # Run synchronously as fallback
        from app.services.import_service import run_import_job
        try:
            run_import_job(db, job.id)
            db.commit()
        except Exception as exc:
            db.rollback()
            failed_job = db.query(ImportJob).filter_by(id=job.id).first()
            if failed_job:
                failed_job.status = "failed"
                failed_job.error_message = f"Queue unavailable ({queue_exc}); synchronous import failed: {exc}"[:2000]
                db.commit()
            import_error = str(exc)

    return {
        "dataset_id": dataset.id,
        "job_id": job.id,
        "is_new_dataset": is_new,
        "filename": dataset.original_filename,
        "dataset_type": dataset_type,
        "file_hash": file_hash,
        "message": (f"Upload saved but import failed: {import_error}" if import_error else
                    "File uploaded. Import job queued." if is_new else "File already imported. New import job created."),
    }


@router.get("/uploads")
def list_uploads(db: Session = Depends(get_db)):
    datasets = db.query(UploadedDataset).order_by(UploadedDataset.created_at.desc()).all()
    return [
        {
            "id": ds.id,
            "filename": ds.original_filename,
            "dataset_type": ds.dataset_type,
            "gateway": ds.gateway,
            "file_size_bytes": ds.file_size_bytes,
            "file_hash": ds.file_hash_sha256,
            "created_at": ds.created_at.isoformat(),
            "import_jobs": [
                {"id": j.id, "status": j.status, "imported_rows": j.imported_rows}
                for j in ds.import_jobs
            ],
        }
        for ds in datasets
    ]


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: str, db: Session = Depends(get_db)):
    ds = db.query(UploadedDataset).filter_by(id=upload_id).first()
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return {
        "id": ds.id,
        "filename": ds.original_filename,
        "dataset_type": ds.dataset_type,
        "gateway": ds.gateway,
        "file_size_bytes": ds.file_size_bytes,
        "file_hash": ds.file_hash_sha256,
        "created_at": ds.created_at.isoformat(),
        "import_jobs": [
            {
                "id": j.id,
                "status": j.status,
                "total_rows": j.total_rows,
                "imported_rows": j.imported_rows,
                "skipped_rows": j.skipped_rows,
                "duplicate_count": j.duplicate_count,
                "warning_count": j.warning_count,
                "error_count": j.error_count,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            }
            for j in ds.import_jobs
        ],
    }
