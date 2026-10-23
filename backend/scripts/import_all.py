import os
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import get_db_ctx
from app.services.import_service import (
    compute_sha256,
    register_dataset,
    create_import_job,
    run_import_job,
)
from app.models.models import (
    SourceRecord, Payment, GatewayTransaction, Refund, UploadedDataset, ImportJob
)

DATA_FILES = [
    ("gwa_payments", "GatewayA_payments_Sep26_dummy.xlsx"),
    ("gwa_transactions", "GatewayA_transactions_Sep26_dummy.xlsx"),
    ("gwa_refunds", "GatewayA_refunds_Sep26_dummy.xlsx"),
    ("gwb_balance", "GatewayB_Sep26_dummy.xlsx"),
]

def run():
    repo_root = Path(__file__).resolve().parent.parent.parent
    data_dir = repo_root / "data"

    print("=" * 60)
    print("FINOPS AI — WORKBOOK INGESTION VERIFICATION")
    print("=" * 60)

    for dtype, fname in DATA_FILES:
        fpath = data_dir / fname
        if not fpath.exists():
            print(f"ERROR: File not found {fpath}")
            sys.exit(1)

        fsize = fpath.stat().st_size
        fhash = compute_sha256(str(fpath))

        print(f"\n--- Ingesting {fname} ({dtype}) ---")
        print(f"File size: {fsize:,} bytes | SHA256: {fhash[:16]}...")

        # Pass 1: Fresh Import
        with get_db_ctx() as db:
            ds, is_new = register_dataset(
                db=db,
                original_filename=fname,
                dataset_type=dtype,
                storage_path=str(fpath),
                file_size=fsize,
                file_hash=fhash,
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            print(f"Registered Dataset: ID={ds.id}, is_new={is_new}")
            job = create_import_job(db, ds.id)
            print(f"Created Import Job: ID={job.id}")
            job = run_import_job(db, job.id)
            status_str = job.status.value if hasattr(job.status, "value") else str(job.status)
            print(f"Job Status: {status_str}")
            print(f"  Total Rows:     {job.total_rows}")
            print(f"  Imported Rows:  {job.imported_rows}")
            print(f"  Duplicates:     {job.duplicate_count}")
            print(f"  Skipped Rows:   {job.skipped_rows}")
            print(f"  Warnings:       {job.warning_count}")
            print(f"  Errors:         {job.error_count}")
            if job.error_message:
                print(f"  Error Message:  {job.error_message}")

        # Pass 2: Idempotency Test (Re-importing same dataset)
        with get_db_ctx() as db:
            ds_re, is_new_re = register_dataset(
                db=db,
                original_filename=fname,
                dataset_type=dtype,
                storage_path=str(fpath),
                file_size=fsize,
                file_hash=fhash,
            )
            job_re = create_import_job(db, ds_re.id)
            job_re = run_import_job(db, job_re.id)
            print(f"  Idempotency Check (Pass 2):")
            print(f"    is_new dataset: {is_new_re} (Expected False)")
            print(f"    Imported:       {job_re.imported_rows} (Expected 0)")
            print(f"    Duplicates:     {job_re.duplicate_count} (Expected {job.imported_rows})")

    # Global Table Counts
    with get_db_ctx() as db:
        print("\n" + "=" * 60)
        print("DATABASE RECORD TOTALS")
        print("=" * 60)
        print(f"Uploaded Datasets:    {db.query(UploadedDataset).count()}")
        print(f"Import Jobs:          {db.query(ImportJob).count()}")
        print(f"Source Records:       {db.query(SourceRecord).count()}")
        print(f"Payments:             {db.query(Payment).count()}")
        print(f"Gateway Transactions: {db.query(GatewayTransaction).count()}")
        print(f"Refunds:              {db.query(Refund).count()}")

if __name__ == "__main__":
    run()
