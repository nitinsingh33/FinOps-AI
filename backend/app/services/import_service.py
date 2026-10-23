"""
Import service — orchestrates file upload, validation, and database persistence.
Idempotent: re-importing same file (same SHA256 + dataset_type) is safe.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.models import (
    ImportJob, ImportRowError, ImportStatus, Payment, GatewayTransaction,
    Refund, Settlement, SourceRecord, UploadedDataset,
)
from app.services.adapters.excel_adapters import parse_dataset

settings = get_settings()
UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/octet-stream",  # Some browsers send this for xlsx
}

SUPPORTED_EXTENSIONS = {".xlsx", ".xls"}

DATASET_TYPE_TO_GATEWAY = {
    "gwa_payments": "gateway_a",
    "gwa_transactions": "gateway_a",
    "gwa_refunds": "gateway_a",
    "gwb_balance": "gateway_b",
}


def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_upload(filename: str, content_type: Optional[str], file_size: int) -> Optional[str]:
    """Return error message if validation fails, None if OK."""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return f"Unsupported file extension '{ext}'. Only .xlsx files are accepted."
    if file_size > settings.max_upload_size_bytes:
        return f"File size {file_size} bytes exceeds maximum {settings.max_upload_size_bytes} bytes."
    return None


def register_dataset(
    db: Session,
    original_filename: str,
    dataset_type: str,
    storage_path: str,
    file_size: int,
    file_hash: str,
    mime_type: Optional[str] = None,
) -> tuple[UploadedDataset, bool]:
    """
    Returns (dataset, is_new). If same hash+type already registered, returns existing.
    """
    existing = (
        db.query(UploadedDataset)
        .filter_by(file_hash_sha256=file_hash, dataset_type=dataset_type)
        .first()
    )
    if existing:
        return existing, False

    gateway = DATASET_TYPE_TO_GATEWAY.get(dataset_type, "unknown")
    ds = UploadedDataset(
        id=str(uuid.uuid4()),
        filename=Path(storage_path).name,
        original_filename=original_filename,
        dataset_type=dataset_type,
        gateway=gateway,
        file_hash_sha256=file_hash,
        file_size_bytes=file_size,
        storage_path=storage_path,
        mime_type=mime_type,
    )
    db.add(ds)
    db.flush()
    return ds, True


def create_import_job(db: Session, dataset_id: str) -> ImportJob:
    job = ImportJob(
        id=str(uuid.uuid4()),
        dataset_id=dataset_id,
        status=ImportStatus.QUEUED,
    )
    db.add(job)
    db.flush()
    return job


def run_import_job(db: Session, job_id: str) -> ImportJob:
    """
    Synchronous import execution. Call from Celery worker or directly.
    Idempotent: checks for existing source records by source_identifier.
    """
    job = db.query(ImportJob).filter_by(id=job_id).first()
    if not job:
        raise ValueError(f"ImportJob {job_id} not found")

    job.status = ImportStatus.PROCESSING
    job.started_at = datetime.now(timezone.utc)
    db.flush()

    dataset = db.query(UploadedDataset).filter_by(id=job.dataset_id).first()
    if not dataset:
        job.status = ImportStatus.FAILED
        job.error_message = f"Dataset {job.dataset_id} not found"
        job.completed_at = datetime.now(timezone.utc)
        db.flush()
        return job

    try:
        parse_result = parse_dataset(dataset.dataset_type, dataset.storage_path)
    except Exception as exc:
        job.status = ImportStatus.FAILED
        job.error_message = str(exc)[:2000]
        job.completed_at = datetime.now(timezone.utc)
        db.flush()
        return job

    job.total_rows = parse_result.total_rows
    imported = 0
    skipped = 0
    duplicate = 0

    # Bulk-insert source records, skipping existing ones
    for rec in parse_result.records:
        src_id = rec["source_identifier"]
        existing_src = (
            db.query(SourceRecord)
            .filter_by(
                gateway=rec["gateway"],
                dataset_type=rec["dataset_type"],
                source_identifier=src_id,
            )
            .first()
        )
        if existing_src:
            duplicate += 1
            continue

        try:
            # Keep the provenance row and normalized entity atomic. A failed
            # row can then be safely retried without an orphan blocking it.
            with db.begin_nested():
                source_rec = SourceRecord(
                    id=str(uuid.uuid4()),
                    dataset_id=dataset.id,
                    job_id=job.id,
                    gateway=rec["gateway"],
                    dataset_type=rec["dataset_type"],
                    source_row_number=rec["source_row_number"],
                    source_identifier=src_id,
                    raw_data=rec["raw_data"],
                    import_warnings=rec.get("import_warnings"),
                )
                db.add(source_rec)
                db.flush()
                _persist_normalized(db, source_rec.id, rec)
                db.flush()
            imported += 1
        except Exception as exc:
            skipped += 1
            parse_result.warnings.append({
                "row_number": rec["source_row_number"],
                "field_name": "__normalize__",
                "message": f"Failed to normalize: {exc}",
                "raw_value": None,
                "severity": "error",
            })

    # Persist row errors/warnings
    for w in parse_result.warnings:
        db.add(ImportRowError(
            id=str(uuid.uuid4()),
            job_id=job.id,
            row_number=w["row_number"],
            severity=w.get("severity", "warning"),
            field_name=w.get("field_name"),
            raw_value=w.get("raw_value"),
            message=w["message"],
        ))

    job.processed_rows = len(parse_result.records) + parse_result.rejected_rows
    job.imported_rows = imported
    job.skipped_rows = skipped + parse_result.rejected_rows
    job.duplicate_count = duplicate
    job.warning_count = len([w for w in parse_result.warnings if w.get("severity") != "error"])
    job.error_count = len([w for w in parse_result.warnings if w.get("severity") == "error"])
    job.completed_at = datetime.now(timezone.utc)
    job.status = (
        ImportStatus.COMPLETED_WITH_WARNINGS
        if (job.warning_count or job.error_count)
        else ImportStatus.COMPLETED
    )
    db.flush()
    return job


def _persist_normalized(db: Session, source_record_id: str, rec: Dict[str, Any]) -> None:
    """Route normalized record to the correct model table."""
    dtype = rec["dataset_type"]

    if dtype == "gwa_payments":
        db.add(Payment(
            id=str(uuid.uuid4()),
            source_record_id=source_record_id,
            gateway=rec["gateway"],
            gateway_payment_id=rec["gateway_payment_id"],
            gateway_order_id=rec.get("gateway_order_id"),
            status=rec["status"],
            payment_method=rec.get("payment_method"),
            gross_amount=rec.get("gross_amount"),
            currency=rec["currency"],
            fee=rec.get("fee"),
            fee_currency=rec.get("fee_currency"),
            tax=rec.get("tax"),
            tax_currency=rec.get("tax_currency"),
            amount_refunded=rec.get("amount_refunded"),
            is_international=rec.get("is_international"),
            is_captured=rec.get("is_captured"),
            card_network=rec.get("card_network"),
            card_type=rec.get("card_type"),
            error_code=rec.get("error_code"),
            transacted_at=rec.get("transacted_at"),
            gateway_metadata=rec.get("gateway_metadata"),
        ))

    elif dtype == "gwa_transactions":
        db.add(GatewayTransaction(
            id=str(uuid.uuid4()),
            source_record_id=source_record_id,
            gateway=rec["gateway"],
            gateway_txn_id=rec["gateway_txn_id"],
            txn_type=rec["txn_type"],
            gateway_payment_id=rec.get("gateway_payment_id"),  # entity_id is the payment id
            gateway_order_id=rec.get("gateway_order_id"),
            settlement_id=rec.get("settlement_id"),
            settlement_utr=rec.get("settlement_utr"),
            gross_amount=rec.get("gross_amount"),
            debit_amount=rec.get("debit_amount"),
            credit_amount=rec.get("credit_amount"),
            fee=rec.get("fee"),
            tax=rec.get("tax"),
            currency=rec["currency"],
            is_settled=rec.get("is_settled"),
            card_network=rec.get("card_network"),
            transacted_at=rec.get("transacted_at"),
            settled_at=rec.get("settled_at"),
            gateway_metadata=rec.get("gateway_metadata"),
        ))
        if rec.get("txn_type") in {"settlement", "offer_settlement"} and rec.get("settlement_id"):
            _accumulate_settlement(db, "gateway_a", rec["settlement_id"], rec["currency"],
                rec.get("gross_amount"), rec.get("fee"), rec.get("tax"),
                rec.get("credit_amount"), rec.get("settled_at"), rec.get("settlement_utr"))
        elif rec.get("txn_type") == "settlement":
            _accumulate_settlement(db, "gateway_a", rec["gateway_txn_id"], rec["currency"],
                rec.get("gross_amount"), rec.get("fee"), rec.get("tax"),
                rec.get("credit_amount"), rec.get("settled_at"), rec.get("settlement_utr"))

    elif dtype == "gwa_refunds":
        db.add(Refund(
            id=str(uuid.uuid4()),
            source_record_id=source_record_id,
            gateway=rec["gateway"],
            gateway_refund_id=rec["gateway_refund_id"],
            gateway_payment_id=rec.get("gateway_payment_id"),
            status=rec["status"],
            amount=rec["amount"],
            currency=rec["currency"],
            arn=rec.get("arn"),
            refunded_at=rec.get("refunded_at"),
        ))

    elif dtype == "gwb_balance":
        db.add(GatewayTransaction(
            id=str(uuid.uuid4()),
            source_record_id=source_record_id,
            gateway=rec["gateway"],
            gateway_txn_id=rec["gateway_txn_id"],
            txn_type=rec["txn_type"],
            reporting_category=rec.get("reporting_category"),
            gateway_payment_id=rec.get("gateway_payment_id"),
            gross_amount=rec.get("gross_amount"),
            fee=rec.get("fee"),
            net_amount=rec.get("net_amount"),
            currency=rec["currency"],
            customer_facing_amount=rec.get("customer_facing_amount"),
            customer_facing_currency=rec.get("customer_facing_currency"),
            country=rec.get("country"),
            card_network=rec.get("card_network"),
            card_brand=rec.get("card_brand"),
            card_funding=rec.get("card_funding"),
            is_settled=rec.get("is_settled"),
            payout_id=rec.get("payout_id"),
            transacted_at=rec.get("transacted_at"),
            settled_at=rec.get("settled_at"),
            available_on=rec.get("available_on"),
            gateway_metadata=rec.get("gateway_metadata"),
        ))
        if rec.get("payout_id"):
            # Gateway B exports balance rows associated with a payout, not a
            # separate authoritative payout amount. Store the currency-scoped
            # sum of those observed rows, clearly labeled by their source ID.
            _accumulate_settlement(db, "gateway_b", rec["payout_id"], rec["currency"],
                rec.get("gross_amount"), rec.get("fee"), rec.get("tax"),
                rec.get("net_amount"), rec.get("settled_at"), None)


def _accumulate_settlement(
    db: Session,
    gateway: str,
    settlement_id: str,
    currency: str,
    gross: Optional[Any],
    fee: Optional[Any],
    tax: Optional[Any],
    net: Optional[Any],
    settled_at: Optional[datetime],
    utr: Optional[str],
) -> None:
    """Accumulate settlement-linked amounts by gateway ID and currency."""
    scoped_id = f"{settlement_id}:{currency}"
    row = db.query(Settlement).filter_by(gateway=gateway, gateway_settlement_id=scoped_id).first()
    if row is None:
        row = Settlement(gateway=gateway, gateway_settlement_id=scoped_id, currency=currency,
                         settlement_utr=utr, gross_amount=None, fee=None, tax=None, net_amount=None)
        db.add(row)
    for field, amount in (("gross_amount", gross), ("fee", fee), ("tax", tax), ("net_amount", net)):
        if amount is not None:
            setattr(row, field, (getattr(row, field) or 0) + amount)
    if settled_at:
        existing_settled_at = row.settled_at
        if existing_settled_at is None:
            row.settled_at = settled_at
        else:
            # SQLite returns timezone-aware DateTime values as naive while
            # PostgreSQL preserves the timezone. Compare both as UTC instants.
            incoming_utc = settled_at.replace(tzinfo=timezone.utc) if settled_at.tzinfo is None else settled_at.astimezone(timezone.utc)
            existing_utc = existing_settled_at.replace(tzinfo=timezone.utc) if existing_settled_at.tzinfo is None else existing_settled_at.astimezone(timezone.utc)
            if incoming_utc > existing_utc:
                row.settled_at = settled_at
