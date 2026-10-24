"""API for vendor GST, TDS, MSME and master-data compliance workflows."""
from __future__ import annotations

from datetime import date
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
import uuid
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.vendor_compliance import (
    RuleApprovalStatus, TaxRule, VendorComplianceException, VendorMaster,
    VendorMasterCleanupItem, VendorScorecard, VendorDocumentImportBatch,
    VendorSourceDocument, VendorInvoice,
)
from app.services.vendor_compliance.compliance_engine import run_vendor_compliance_checks
from app.services.vendor_compliance.synthetic_data import seed_vendor_compliance_data
from app.services.vendor_compliance.gst_checks import validate_gstin_format, validate_pan_format, check_pan_gstin_consistency
from app.services.vendor_compliance.msme_checks import validate_msme_udyam_format
from app.services.vendor_compliance.pdf_ingestion import files_from_uploads, import_documents

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
        "total_amount_at_stake": (str(s.total_amount_at_stake) if (s.evidence_coverage or {}).get("amount_at_stake_available", True) else None), "currency": s.currency,
        "summary_reasons": s.summary_reasons or [], "evidence_coverage": s.evidence_coverage or {},
        "recommended_actions": s.recommended_actions or [],
        "last_assessed_at": s.last_assessed_at.isoformat() if s.last_assessed_at else None,
    }


@router.post("/seed")
def seed_synthetic_data(db: Session = Depends(get_db)):
    counts = seed_vendor_compliance_data(db)
    return {"created": counts, "synthetic": True, "notice": "Synthetic data is for demonstration only."}


@router.post("/documents/import")
async def import_invoice_documents(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    """Import PDF or ZIP payloads; ZIP members are processed in memory and never extracted."""
    if not files:
        raise HTTPException(status_code=422, detail="Select at least one PDF or ZIP file")
    uploads = []
    total = 0
    for upload in files:
        data = await upload.read(100 * 1024 * 1024 + 1)
        total += len(data)
        if total > 100 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Upload exceeds the 100 MB total limit")
        uploads.append((upload.filename or "document.pdf", data))
    try:
        docs = files_from_uploads(uploads)
        if not docs:
            raise ValueError("No PDF documents were found in the upload")
        result = import_documents(db, docs, "zip" if any(n.lower().endswith(".zip") for n, _ in uploads) else "pdf")
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/documents")
def list_invoice_documents(batch_id: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(VendorSourceDocument)
    if batch_id:
        query = query.filter_by(import_batch_id=batch_id)
    return [{"id": d.id, "batch_id": d.import_batch_id, "filename": d.source_filename,
             "sha256": d.source_sha256, "document_type": d.document_type,
             "extraction_status": d.extraction_status, "mapping_status": d.mapping_status,
             "review_required": d.review_required, "review_reasons": d.review_reasons or [],
             "fields": d.extracted_fields or {}, "vendor_id": d.vendor_id, "invoice_id": d.invoice_id,
             "imported_at": d.imported_at.isoformat() if d.imported_at else None,
             "extraction_error": d.extraction_error}
            for d in query.order_by(VendorSourceDocument.imported_at.desc()).limit(1000).all()]


@router.get("/documents/batches")
def list_document_batches(db: Session = Depends(get_db)):
    return [{"id": b.id, "dataset_name": b.dataset_name, "source_kind": b.source_kind,
             "total_files": b.total_files, "parsed_files": b.parsed_files,
             "failed_files": b.failed_files, "duplicate_files": b.duplicate_files,
             "review_required_files": b.review_required_files,
             "created_at": b.created_at.isoformat() if b.created_at else None}
            for b in db.query(VendorDocumentImportBatch).order_by(VendorDocumentImportBatch.created_at.desc()).limit(100).all()]


def _source_vendor_ids(db: Session, source: str | None):
    if source == "synthetic":
        return [row.id for row in db.query(VendorMaster.id).filter_by(is_synthetic=True).all()]
    if source == "hr":
        return [row.vendor_id for row in db.query(VendorSourceDocument.vendor_id).filter(
            VendorSourceDocument.vendor_id.is_not(None)
        ).distinct().all()]
    return None


@router.get("/documents/export.csv")
def export_invoice_documents(db: Session = Depends(get_db)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["source_filename", "document_type", "extraction_status", "mapping_status", "review_required", "vendor_name", "supplier_gstin", "invoice_number", "invoice_date", "currency", "total_invoice_value", "review_reasons", "sha256"])
    for doc in db.query(VendorSourceDocument).order_by(VendorSourceDocument.source_filename).all():
        fields = doc.extracted_fields or {}
        val = lambda key: (fields.get(key) or {}).get("value")
        writer.writerow([doc.source_filename, doc.document_type, doc.extraction_status, doc.mapping_status,
                         doc.review_required, val("vendor_legal_name"), val("supplier_gstin"), val("invoice_number"),
                         val("invoice_date"), val("currency"), val("total_invoice_value"),
                         "; ".join(doc.review_reasons or []), doc.source_sha256])
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vendor_invoice_import_review.csv"})


@router.get("/reports/{report_name}.csv")
def export_vendor_report(report_name: str, source: str = "hr", db: Session = Depends(get_db)):
    if report_name not in ("scorecards", "exceptions", "cleanup"):
        raise HTTPException(status_code=404, detail="Unknown vendor report")
    if source not in ("hr", "synthetic", "all"):
        raise HTTPException(status_code=422, detail="source must be hr, synthetic, or all")
    ids = _source_vendor_ids(db, source)
    output = io.StringIO()
    writer = csv.writer(output)
    if report_name == "scorecards":
        writer.writerow(["vendor_code", "vendor_name", "gstin", "pan", "status", "risk_score", "gst_status", "tds_status", "msme_status", "invoice_count", "document_count", "amount_at_stake", "currency", "summary_reasons"])
        query = db.query(VendorScorecard, VendorMaster).join(VendorMaster, VendorMaster.id == VendorScorecard.vendor_id)
        if ids is not None: query = query.filter(VendorScorecard.vendor_id.in_(ids))
        for s, v in query.order_by(VendorMaster.vendor_code).all():
            coverage = s.evidence_coverage or {}
            amount = s.total_amount_at_stake if coverage.get("amount_at_stake_available", True) else ""
            writer.writerow([v.vendor_code, v.legal_name, v.gstin, v.pan, s.status, s.risk_score, s.gst_status, s.tds_status, s.msme_status, coverage.get("invoices_checked", 0), coverage.get("source_documents", 0), amount, s.currency, "; ".join(s.summary_reasons or [])])
    elif report_name == "exceptions":
        writer.writerow(["vendor_code", "vendor_name", "source_invoice", "source_document", "category", "check_code", "severity", "title", "description", "evidence", "missing_information", "amount_at_stake", "currency", "suggested_action"])
        query = db.query(VendorComplianceException, VendorMaster).join(VendorMaster, VendorMaster.id == VendorComplianceException.vendor_id)
        if ids is not None: query = query.filter(VendorComplianceException.vendor_id.in_(ids))
        for e, v in query.order_by(VendorMaster.vendor_code, VendorComplianceException.created_at).all():
            source_doc = db.query(VendorSourceDocument).filter_by(invoice_id=e.invoice_id).first() if e.invoice_id else None
            invoice_number = db.query(VendorInvoice.invoice_number).filter_by(id=e.invoice_id).scalar() if e.invoice_id else ""
            writer.writerow([v.vendor_code, v.legal_name, invoice_number or "", source_doc.source_filename if source_doc else "", e.category, e.check_code, e.severity, e.title, e.description, str(e.evidence or {}), "; ".join(e.missing_information or []), e.amount_at_stake, e.currency, e.suggested_action])
        # Include staged documents that cannot safely map to an ordinary invoice/vendor record.
        for doc in db.query(VendorSourceDocument).filter(VendorSourceDocument.review_required.is_(True)).all():
            fields = doc.extracted_fields or {}
            value = lambda key: (fields.get(key) or {}).get("value")
            if ids is not None and doc.vendor_id not in ids:
                # Unmapped HR source documents belong to the HR report; no synthetic rows are mixed in.
                if source != "hr": continue
            for reason in doc.review_reasons or ["Manual review required."]:
                evidence = {key: entry.get("value") for key, entry in fields.items() if entry.get("status") == "extracted"}
                writer.writerow([value("vendor_legal_name") or "Unresolved vendor", value("vendor_legal_name") or "Unresolved vendor", value("invoice_number") or "", doc.source_filename, "document_review", "SOURCE_DOCUMENT_REVIEW", "medium", f"Review {doc.document_type.replace('_', ' ')}: {doc.source_filename}", reason, str(evidence), "Human review of source document and missing evidence", "", value("currency") or "", "Review the source document and attach the external evidence required for the requested compliance conclusion."])
    else:
        writer.writerow(["vendor_code", "vendor_name", "source_documents", "field_name", "issue_type", "severity", "description", "recommended_fix", "status"])
        query = db.query(VendorMasterCleanupItem, VendorMaster).join(VendorMaster, VendorMaster.id == VendorMasterCleanupItem.vendor_id)
        if ids is not None: query = query.filter(VendorMasterCleanupItem.vendor_id.in_(ids))
        for item, v in query.order_by(VendorMaster.vendor_code).all():
            source_names = [d.source_filename for d in db.query(VendorSourceDocument).filter_by(vendor_id=v.id).all()]
            writer.writerow([v.vendor_code, v.legal_name, "; ".join(source_names), item.field_name, item.issue_type, item.severity, item.description, item.recommended_fix, item.status])
    filename = f"vendor_{report_name}_{source}.csv"
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"})


@router.get("/vendors")
def list_vendors(q: Optional[str] = None, source: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(VendorMaster)
    source_ids = _source_vendor_ids(db, source)
    if source_ids is not None:
        query = query.filter(VendorMaster.id.in_(source_ids))
    if q:
        term = f"%{q}%"
        query = query.filter(or_(VendorMaster.vendor_code.ilike(term), VendorMaster.legal_name.ilike(term)))
    vendors = query.order_by(VendorMaster.vendor_code).all()
    scorecards = {s.vendor_id: s for s in db.query(VendorScorecard).all()}
    return [_vendor(v, scorecards.get(v.id)) for v in vendors]


@router.post("/checks/run")
def run_checks(vendor_id: Optional[str] = None, source: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(VendorMaster)
    source_ids = _source_vendor_ids(db, source)
    if source_ids is not None:
        query = query.filter(VendorMaster.id.in_(source_ids))
    if vendor_id:
        query = query.filter_by(id=vendor_id)
    vendors = query.order_by(VendorMaster.vendor_code).all()
    if vendor_id and not vendors:
        raise HTTPException(status_code=404, detail="Vendor not found")
    scorecards = [run_vendor_compliance_checks(db, v.id) for v in vendors]
    db.commit()
    return {"assessed": len(scorecards), "scorecards": [_scorecard(s) for s in scorecards]}


@router.get("/scorecards")
def list_scorecards(status: Optional[str] = None, source: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(VendorScorecard)
    ids = _source_vendor_ids(db, source)
    if ids is not None: query = query.filter(VendorScorecard.vendor_id.in_(ids))
    if status:
        query = query.filter_by(status=status)
    return [_scorecard(s) for s in query.order_by(VendorScorecard.risk_score.desc()).all()]


@router.get("/exceptions")
def list_exceptions(category: Optional[str] = None, status: Optional[str] = None,
                    vendor_id: Optional[str] = None, source: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(VendorComplianceException)
    if category: query = query.filter_by(category=category)
    if status: query = query.filter_by(review_status=status)
    if vendor_id: query = query.filter_by(vendor_id=vendor_id)
    ids = _source_vendor_ids(db, source)
    if ids is not None: query = query.filter(VendorComplianceException.vendor_id.in_(ids))
    rows = query.order_by(VendorComplianceException.created_at.desc()).limit(1000).all()
    return [{"id": e.id, "vendor_id": e.vendor_id, "invoice_id": e.invoice_id,
             "source_filename": (db.query(VendorSourceDocument.source_filename).filter_by(invoice_id=e.invoice_id).scalar() if e.invoice_id else None),
             "invoice_number": (db.query(VendorInvoice.invoice_number).filter_by(id=e.invoice_id).scalar() if e.invoice_id else None),
             "check_code": e.check_code,
             "category": e.category, "severity": e.severity, "title": e.title,
             "description": e.description, "amount_at_stake": str(e.amount_at_stake) if e.amount_at_stake is not None else None,
             "currency": e.currency, "missing_information": e.missing_information or [],
             "suggested_action": e.suggested_action,
             "review_status": e.review_status, "is_synthetic_warning": e.is_synthetic_warning}
            for e in rows]


@router.post("/master-cleanup/scan")
def scan_vendor_master(source: Optional[str] = None, db: Session = Depends(get_db)):
    """Create actionable cleanup findings while preserving vendor source values."""
    scoped_ids = _source_vendor_ids(db, source)
    delete_query = db.query(VendorMasterCleanupItem).filter_by(status="open")
    if scoped_ids is not None:
        delete_query = delete_query.filter(VendorMasterCleanupItem.vendor_id.in_(scoped_ids))
    delete_query.delete(synchronize_session=False)
    findings = []
    vendors_query = db.query(VendorMaster)
    vendor_ids = _source_vendor_ids(db, source)
    if vendor_ids is not None:
        vendors_query = vendors_query.filter(VendorMaster.id.in_(vendor_ids))
    vendors = vendors_query.all()
    for v in vendors:
        hr_foreign = v.vendor_type == "foreign" and not v.is_synthetic
        checks = []
        if v.pan and not validate_pan_format(v.pan)[0]:
            checks.append(("invalid_pan", "pan", "PAN format is invalid", "Collect and verify PAN evidence."))
        if not v.pan and not hr_foreign:
            checks.append(("missing_pan", "pan", "PAN is not present in the imported vendor evidence.", "Obtain PAN documentation and verify operative status."))
        elif not v.is_pan_verified:
            checks.append(("pan_unverified", "pan", "PAN format was read but operative status and ownership are not verified.", "Verify PAN operative status and ownership using authoritative tax-team evidence."))
        if v.gstin and not validate_gstin_format(v.gstin)[0]:
            checks.append(("invalid_gstin", "gstin", "GSTIN format is invalid", "Collect GST registration evidence."))
        if not v.gstin and not hr_foreign:
            checks.append(("missing_gstin", "gstin", "GSTIN is not present in the imported vendor evidence.", "Confirm GST registration status or document the verified non-registration basis."))
        elif not v.is_gstin_verified:
            checks.append(("gstin_unverified", "gstin", "GSTIN format was read but active registration was not verified.", "Verify active registration using an authoritative GST source."))
        if v.pan and v.gstin and validate_pan_format(v.pan)[0] and validate_gstin_format(v.gstin)[0] and not check_pan_gstin_consistency(v.pan, v.gstin)[0]:
            checks.append(("pan_gstin_mismatch", "gstin", "PAN does not match the PAN embedded in GSTIN", "Confirm the legal identity with the vendor."))
        if v.msme_type != "non_msme" and not v.udyam_number:
            checks.append(("missing_udyam", "udyam_number", "MSME registration evidence is missing", "Obtain and verify the Udyam certificate."))
        if v.msme_type == "unknown":
            checks.append(("unknown_msme_classification", "msme_type", "The documents do not establish the vendor's current micro/small/medium classification.", "Verify current enterprise classification from source evidence before applying MSME deadline checks."))
        elif v.msme_type != "non_msme" and not v.is_msme_verified:
            checks.append(("msme_unverified", "udyam_number", "MSME/Udyam declaration is present but not independently verified.", "Verify the Udyam certificate and current enterprise classification."))
        if v.msme_type != "non_msme" and v.udyam_number and not validate_msme_udyam_format(v.udyam_number)[0]:
            checks.append(("invalid_udyam", "udyam_number", "Udyam number format is invalid", "Confirm the Udyam number against source evidence."))
        for issue, field, description, fix in checks:
            item = VendorMasterCleanupItem(id=str(uuid.uuid4()), vendor_id=v.id, issue_type=issue,
                severity="high" if issue in ("invalid_pan", "invalid_gstin", "pan_gstin_mismatch") else "medium",
                field_name=field, description=description, recommended_fix=fix, status="open")
            db.add(item); findings.append(item)
        if v.pan:
            duplicate = db.query(VendorMaster).filter(VendorMaster.id != v.id, VendorMaster.pan == v.pan, VendorMaster.is_synthetic == v.is_synthetic).order_by(VendorMaster.id).first()
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
def list_master_cleanup(status: Optional[str] = "open", source: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(VendorMasterCleanupItem)
    ids = _source_vendor_ids(db, source)
    if ids is not None: query = query.filter(VendorMasterCleanupItem.vendor_id.in_(ids))
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
