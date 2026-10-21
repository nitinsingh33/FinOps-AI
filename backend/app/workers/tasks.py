"""Celery task definitions."""
import structlog

from app.workers.celery_app import celery_app
from app.db.session import get_db_ctx

logger = structlog.get_logger()


@celery_app.task(name="run_import_task", bind=True, max_retries=3)
def run_import_task(self, job_id: str):
    logger.info("import_task_started", job_id=job_id)
    with get_db_ctx() as db:
        from app.services.import_service import run_import_job
        job = run_import_job(db, job_id)
    logger.info("import_task_completed", job_id=job_id, status=job.status)


@celery_app.task(name="run_reconciliation_task", bind=True, max_retries=2)
def run_reconciliation_task(self, run_id: str):
    logger.info("reconciliation_task_started", run_id=run_id)
    with get_db_ctx() as db:
        from app.services.reconciliation.engine import run_reconciliation
        run = run_reconciliation(db, run_id)
    logger.info("reconciliation_task_completed", run_id=run_id, status=run.status)
