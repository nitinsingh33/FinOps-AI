"""Regression tests for safe, idempotent HR invoice document ingestion."""
from __future__ import annotations

import io
import zipfile

import pytest
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.vendor_compliance import VendorDocumentImportBatch, VendorSourceDocument
from app.services.vendor_compliance import pdf_ingestion as ingestion
from app.api.v1.routers.vendor_compliance import export_vendor_report


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_empty_and_malformed_pdfs_are_reported_without_batch_crash():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    empty = io.BytesIO()
    writer.write(empty)
    fields, kind, error = ingestion.extract_invoice_fields(empty.getvalue())
    assert fields == {}
    assert kind == "failed"
    assert "No selectable text" in error
    with pytest.raises(Exception):
        ingestion.extract_invoice_fields(b"not a PDF")


def test_zip_path_traversal_and_malformed_archive_are_rejected():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("../escape.pdf", b"pdf")
    with pytest.raises(ValueError, match="Unsafe archive path"):
        ingestion.files_from_uploads([("invoices.zip", out.getvalue())])
    with pytest.raises(ValueError, match="malformed"):
        ingestion.files_from_uploads([("broken.zip", b"not a zip")])


def test_hash_duplicate_reimport_does_not_duplicate_document(db, monkeypatch):
    fields = {
        "vendor_legal_name": {"value": "Sample Supplier", "status": "extracted", "evidence": "Supplier"},
        "invoice_number": {"value": "S-1", "status": "extracted", "evidence": "S-1"},
    }
    monkeypatch.setattr(ingestion, "extract_invoice_fields", lambda _: (fields, "invoice", None))
    first = ingestion.import_documents(db, [("one.pdf", b"unique pdf bytes")], "pdf")
    second = ingestion.import_documents(db, [("renamed.pdf", b"unique pdf bytes")], "pdf")
    assert first["parsed_files"] == 1
    assert first["review_required_files"] == 1
    assert second["duplicate_files"] == 1
    assert db.query(VendorSourceDocument).count() == 1
    assert db.query(VendorDocumentImportBatch).count() == 2
    response = export_vendor_report("exceptions", source="hr", db=db)
    assert response.headers["content-disposition"] == "attachment; filename=vendor_exceptions_hr.csv"


def test_each_extraction_failure_is_isolated(monkeypatch, db):
    monkeypatch.setattr(ingestion, "extract_invoice_fields", lambda _: (_ for _ in ()).throw(ValueError("malformed")))
    result = ingestion.import_documents(db, [("bad.pdf", b"bad"), ("also-bad.pdf", b"bad2")], "pdf")
    assert result["failed_files"] == 2
    assert result["parsed_files"] == 0
    assert result["review_required_files"] == 2
    assert all(row["status"] == "failed" for row in result["documents"])
