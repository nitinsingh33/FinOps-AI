"""Safe, source-traceable ingestion for selectable-text vendor invoice PDFs."""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.models.vendor_compliance import (
    VendorDocumentImportBatch, VendorSourceDocument, VendorMaster, VendorInvoice,
)

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_BATCH_BYTES = 100 * 1024 * 1024
MAX_FILES = 200


def _field(value: Any = None, status: str = "missing", evidence: str | None = None) -> dict[str, Any]:
    return {"value": value, "status": status, "evidence": evidence}


def _date(text: str) -> date | None:
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _money(text: str) -> Decimal | None:
    cleaned = re.sub(r"[^0-9.,()-]", "", text).replace(",", "")
    if not cleaned:
        return None
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _find(text: str, pattern: str, flags: int = re.I) -> tuple[str | None, str | None]:
    match = re.search(pattern, text, flags)
    return (match.group(1).strip(), match.group(0).strip()) if match else (None, None)


def extract_invoice_fields(pdf_bytes: bytes) -> tuple[dict[str, Any], str, str | None]:
    """Extract explicit text facts. No OCR or inferred numeric values are used."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF import requires pypdf; install backend requirements.") from exc
    if len(pdf_bytes) > MAX_FILE_BYTES:
        raise ValueError("PDF exceeds the 20 MB per-file limit")
    reader = PdfReader(io.BytesIO(pdf_bytes), strict=False)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are not supported")
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        return {}, "failed", "No selectable text; OCR is not configured."
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    normalized = "\n".join(lines)

    type_match = next((kind for kind in ("proforma invoice", "debit note", "credit note", "bill of supply", "cash memo", "tax invoice", "invoice")
                       if any(line.casefold() == kind for line in lines)), None)
    if type_match == "proforma invoice": doc_type = "proforma_invoice"
    elif type_match == "debit note": doc_type = "debit_note"
    elif type_match == "credit note": doc_type = "credit_note"
    elif type_match == "tax invoice": doc_type = "tax_invoice"
    elif type_match == "bill of supply": doc_type = "bill_of_supply"
    elif type_match == "cash memo": doc_type = "cash_memo"
    elif type_match == "invoice": doc_type = "invoice"
    else: doc_type = "unknown"

    def labeled(label_pattern: str, value_pattern: str = r"([^\n]+)") -> tuple[str | None, str | None]:
        return _find(normalized, rf"(?:{label_pattern})\s*[:#-]?\s*\n?\s*{value_pattern}")

    name = None
    name_index = None
    supplier_address_start = None
    gstin_line = next((line for line in lines if re.search(r"\bGSTIN\s*:", line, re.I)), None)
    if gstin_line:
        gstin_idx = lines.index(gstin_line)
        candidates = [(i, x) for i, x in enumerate(lines[:gstin_idx]) if not re.search(r"^(?:state\s*:|pan\s*:|udyam|tax invoice|invoice)$", x, re.I)]
        if candidates:
            name_index = candidates[0][0]
            addr_idx = next((i for i, x in candidates[1:] if re.match(r"^(?:\d+[A-Za-z-]*\s|H\.?(?:No)?\.?\s|Plot\s|Shop\s|SCO\s|Unit\s|B-\d|C-\d|A-\d|RZ-\d|WZ-\d|E-\d|Flat\s|Chamber\s)", x, re.I)), None)
            if addr_idx is None:
                addr_idx = next((i for i, x in candidates[1:] if re.search(r"\b(?:Nagar|Road|Street|Market|Industrial Area|Sector|Colony|Complex|Park|House|Floor)\b", x, re.I)), gstin_idx)
            supplier_address_start = addr_idx
            name = " ".join(x for i, x in candidates if i < addr_idx).strip() or candidates[0][1]
    if not name:
        invoice_idx = next((i for i, x in enumerate(lines) if x.casefold() in ("invoice", "tax invoice", "proforma invoice", "debit note", "credit note")), None)
        if invoice_idx is not None:
            name = next((x for x in lines[invoice_idx + 1:] if not re.match(r"^(invoice no\.?|date|bill to)$", x, re.I)), None)
            name_index = lines.index(name) if name else None
            if name_index is not None:
                supplier_address_start = name_index + 1

    invoice_no, inv_ev = labeled(r"Invoice\s+No\.?|Note\s+No\.?|Credit\s+Note\s+No\.?", r"([^\n]+)")
    # In extracted PDFs labels and values may occupy separate lines; capture the first non-label line.
    invoice_no = re.sub(r"^(?:Invoice No\.?|Note No\.?)\s*", "", invoice_no or "", flags=re.I).strip() or None
    date_text, date_ev = labeled(r"Date", r"([^\n]+)")
    date_text = re.sub(r"^Date\s*", "", date_text or "", flags=re.I).strip()
    invoice_date = _date(date_text) if date_text else None
    bill_to_idx = next((i for i, line in enumerate(lines) if re.match(r"Bill\s+to\b", line, re.I)), None)
    seller_text = "\n".join(lines[:bill_to_idx]) if bill_to_idx is not None else normalized
    buyer_text = "\n".join(lines[bill_to_idx + 1:]) if bill_to_idx is not None else ""

    def amount(label: str) -> tuple[Decimal | None, str | None]:
        val, ev = _find(normalized, rf"(?:{label})\s*(?:\([^\n)]*(?:[A-Z]{{3}}|Rs\.?|₹)[^\n)]*\))?\s*[:\-]?\s*(?:@\s*[\d.]+\s*%)?\s*(?:[A-Z]{{3}}|Rs\.?|₹)?\s*([\d,]+(?:\.\d{{1,2}})?)")
        return (_money(val) if val is not None else None, ev)

    # Prefer the invoice summary line. The table column header can be followed
    # by a quantity (often "1"), which must never be mistaken for an amount.
    taxable, taxable_ev = amount(r"Total\s+Taxable\s+(?:Value|Amount)|Assessable\s+Value")
    total, total_ev = amount(r"(?:Invoice\s+Total|Grand\s+Total(?:\s+Invoice)?|Total\s+Invoice\s+Value|Total\s+Amount|Amount\s+Payable)")
    cgst, cgst_ev = amount(r"CGST(?:\s+Amount)?(?:\s*@\s*[\d.]+\s*%)?")
    sgst, sgst_ev = amount(r"SGST(?:/UTGST)?(?:\s+Amount)?(?:\s*@\s*[\d.]+\s*%)?|UTGST(?:\s+Amount)?")
    igst, igst_ev = amount(r"IGST(?:\s+Amount)?(?:\s*@\s*[\d.]+\s*%)?")
    cess, cess_ev = amount(r"Cess(?:\s+Amount)?")
    discount, discount_ev = amount(r"Discount")
    freight, freight_ev = amount(r"Freight|Shipping")
    tax_total_explicit, tax_total_ev = amount(r"Total\s+Tax(?:\s+Amount)?")
    rate, rate_ev = _find(normalized, r"(?:GST|CGST|SGST|IGST)\s*@\s*([0-9]+(?:\.[0-9]+)?\s*%)")
    gstin, gstin_ev = _find(seller_text, r"GSTIN\s*:\s*([0-9A-Z]{15})")
    pan, pan_ev = _find(seller_text, r"PAN\s*:\s*([A-Z]{5}[0-9]{4}[A-Z])")
    udyam, udyam_ev = _find(normalized, r"(UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7})")
    msme_type, msme_ev = _find(normalized, r"\b(Micro|Small|Medium)\s+Enterprise\b")
    supplier_address = None
    if supplier_address_start is not None:
        address_lines = []
        for line in lines[supplier_address_start:]:
            if re.match(r"^(State\s*:|GSTIN\s*:|PAN\s*:|Udyam\b|TAX INVOICE\b|INVOICE\b|PROFORMA INVOICE\b|DEBIT NOTE\b|CREDIT NOTE\b|Invoice\s+No\.?|Note\s+No\.?|Date\b|Bill\s+to\b|#\s*$)", line, re.I):
                break
            address_lines.append(line)
        supplier_address = ", ".join(address_lines) or None
    buyer_name = lines[bill_to_idx + 1] if bill_to_idx is not None and bill_to_idx + 1 < len(lines) else None
    buyer_address = None
    if bill_to_idx is not None:
        buyer_parts = []
        for line in lines[bill_to_idx + 2:]:
            if re.search(r"GSTIN\s*:|State\s*:", line, re.I) or line.casefold() in ("#", "description"):
                break
            buyer_parts.append(line)
        buyer_address = ", ".join(buyer_parts) or None
    supplier_state, state_ev = _find(seller_text, r"State\s*:\s*[^\n(]+\(Code\s*(\d{2})\)")
    pos, pos_ev = _find(normalized, r"Place\s+of\s+Supply\s*:?\s*[^\n(]*\(?([0-9]{2})\)?")
    currency = "INR" if re.search(r"(?:₹|\bINR\b|\bRs\.?\s*[\d,])", normalized, re.I) else None
    if re.search(r"\bUSD\b|\$\s*[\d,]", normalized): currency = "USD"
    elif re.search(r"\bGBP\b|£\s*[\d,]", normalized): currency = "GBP"
    rcm, rcm_ev = _find(normalized, r"Reverse\s+Charge\s*:?\s*(Yes|No|Applicable|Not Applicable)")
    terms, terms_ev = _find(normalized, r"Payment\s+Terms\s*:?\s*([^\n]+)")
    due, due_ev = _find(normalized, r"Due\s+Date\s*:?\s*([^\n]+)")
    po, po_ev = _find(normalized, r"(?:Purchase\s+Order|PO)\s*(?:No\.?|Number)?\s*:?\s*([^\n]+)")

    buyer_gstins = re.findall(r"\bGSTIN\s*:\s*([0-9A-Z]{15})", buyer_text)
    foreign_tax_id, foreign_tax_ev = _find(normalized, r"(?:Tax\s+ID|VAT\s+No\.?)\s*(?:\([^\n)]*\))?\s*:\s*([A-Z0-9][A-Z0-9 -]{4,24})")
    if foreign_tax_id:
        foreign_tax_id = foreign_tax_id.strip(" .")
    fields = {
        "vendor_legal_name": _field(name, "extracted" if name else "missing", name),
        "vendor_address": _field(supplier_address, "extracted" if supplier_address else "missing", supplier_address),
        "supplier_gstin": _field(gstin, "extracted" if gstin else ("missing" if "GSTIN" not in seller_text else "ambiguous"), gstin_ev),
        "supplier_pan": _field(pan, "extracted" if pan else ("missing" if "PAN" not in seller_text else "ambiguous"), pan_ev),
        "foreign_tax_id": _field(foreign_tax_id, "extracted" if foreign_tax_id else "missing", foreign_tax_ev),
        "vendor_state_code": _field(supplier_state, "extracted" if supplier_state else "missing", state_ev),
        "buyer_legal_name": _field(buyer_name, "extracted" if buyer_name else "missing", buyer_name),
        "buyer_address": _field(buyer_address, "extracted" if buyer_address else "missing", buyer_address),
        "buyer_gstin": _field(buyer_gstins[0] if buyer_gstins else None, "extracted" if buyer_gstins else "missing", buyer_gstins[0] if buyer_gstins else None),
        "udyam_number": _field(udyam, "extracted" if udyam else ("missing" if "Udyam" not in normalized else "ambiguous"), udyam_ev),
        "msme_type": _field(msme_type.casefold() if msme_type else None, "extracted" if msme_type else ("missing" if "Udyam" not in normalized else "ambiguous"), msme_ev),
        "invoice_number": _field(invoice_no, "extracted" if invoice_no else "missing", inv_ev),
        "invoice_date": _field(invoice_date.isoformat() if invoice_date else None, "extracted" if invoice_date else ("ambiguous" if date_text else "missing"), date_ev),
        "document_type": _field(doc_type, "extracted" if doc_type != "unknown" else "ambiguous"),
        "currency": _field(currency, "extracted" if currency else "missing", currency),
        "place_of_supply_state_code": _field(pos, "extracted" if pos else "missing", pos_ev),
        "taxable_value": _field(str(taxable) if taxable is not None else None, "extracted" if taxable is not None else "missing", taxable_ev),
        "discount": _field(str(discount) if discount is not None else None, "extracted" if discount is not None else "missing", discount_ev),
        "freight": _field(str(freight) if freight is not None else None, "extracted" if freight is not None else "missing", freight_ev),
        "cgst_amount": _field(str(cgst) if cgst is not None else None, "extracted" if cgst is not None else "missing", cgst_ev),
        "sgst_amount": _field(str(sgst) if sgst is not None else None, "extracted" if sgst is not None else "missing", sgst_ev),
        "igst_amount": _field(str(igst) if igst is not None else None, "extracted" if igst is not None else "missing", igst_ev),
        "cess_amount": _field(str(cess) if cess is not None else None, "extracted" if cess is not None else "missing", cess_ev),
        "stated_gst_rate": _field(rate, "extracted" if rate else "missing", rate_ev),
        "explicit_total_tax": _field(str(tax_total_explicit) if tax_total_explicit is not None else None, "extracted" if tax_total_explicit is not None else "missing", tax_total_ev),
        "total_invoice_value": _field(str(total) if total is not None else None, "extracted" if total is not None else "missing", total_ev),
        "reverse_charge": _field(rcm, "extracted" if rcm else ("missing" if "Reverse Charge" not in normalized else "ambiguous"), rcm_ev),
        "payment_terms": _field(terms, "extracted" if terms else "missing", terms_ev),
        "due_date": _field(due, "extracted" if due else "missing", due_ev),
        "purchase_order": _field(po, "extracted" if po else "missing", po_ev),
    }
    return fields, doc_type, None


def _safe_pdf_entries(files: Iterable[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    output: list[tuple[str, bytes]] = []
    total = 0
    for filename, data in files:
        posix, windows = PurePosixPath(filename), PureWindowsPath(filename)
        if posix.is_absolute() or windows.is_absolute() or ".." in posix.parts or ".." in windows.parts or windows.drive:
            raise ValueError("Unsafe archive path detected")
        if not filename.lower().endswith(".pdf"):
            continue
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("An input PDF exceeds the 20 MB per-file limit")
        total += len(data)
        if total > MAX_BATCH_BYTES:
            raise ValueError("Import exceeds the 100 MB total size limit")
        output.append((PurePosixPath(filename).name, data))
        if len(output) > MAX_FILES:
            raise ValueError("Import exceeds the 200 PDF file limit")
    return output


def files_from_uploads(uploads: Iterable[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    expanded: list[tuple[str, bytes]] = []
    for filename, data in uploads:
        if filename.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    for item in archive.infolist():
                        if item.is_dir():
                            continue
                        # Validate every entry path, even ignored non-PDF members.
                        posix, windows = PurePosixPath(item.filename), PureWindowsPath(item.filename)
                        if posix.is_absolute() or windows.is_absolute() or ".." in posix.parts or ".." in windows.parts or windows.drive:
                            raise ValueError("Unsafe archive path detected")
                        if item.filename.lower().endswith(".pdf"):
                            if item.file_size > MAX_FILE_BYTES:
                                raise ValueError("An archive PDF exceeds the 20 MB per-file limit")
                            if sum(len(payload) for _, payload in expanded) + item.file_size > MAX_BATCH_BYTES:
                                raise ValueError("Import exceeds the 100 MB total size limit")
                            with archive.open(item) as stream:
                                expanded.append((item.filename, stream.read(MAX_FILE_BYTES + 1)))
            except zipfile.BadZipFile as exc:
                raise ValueError("The uploaded ZIP file is malformed") from exc
        elif filename.lower().endswith(".pdf"):
            expanded.append((filename, data))
        else:
            raise ValueError("Upload a PDF or ZIP containing PDFs")
    return _safe_pdf_entries(expanded)


def import_documents(db: Session, files: list[tuple[str, bytes]], source_kind: str) -> dict[str, Any]:
    files = _safe_pdf_entries(files)
    batch = VendorDocumentImportBatch(source_kind=source_kind, total_files=len(files))
    db.add(batch)
    db.flush()
    results = []
    for filename, data in files:
        digest = hashlib.sha256(data).hexdigest()
        existing = db.query(VendorSourceDocument).filter_by(source_sha256=digest).first()
        if existing:
            batch.duplicate_files += 1
            results.append({"filename": filename, "status": "duplicate", "document_id": existing.id})
            continue
        extracted, doc_type, error = {}, "unknown", None
        try:
            extracted, doc_type, error = extract_invoice_fields(data)
        except Exception as exc:  # isolate malformed documents; do not expose PDF text or parser details
            error = f"PDF extraction failed ({type(exc).__name__})."
        extraction_status = "failed" if error and not extracted else "parsed"
        review_reasons = []
        if extraction_status == "failed": review_reasons.append(error or "Text extraction failed")
        if doc_type != "tax_invoice": review_reasons.append(f"Document type is {doc_type}; ordinary tax-invoice mapping was not applied.")
        required = ("vendor_legal_name", "invoice_number", "invoice_date", "taxable_value", "total_invoice_value", "currency")
        missing = [key for key in required if extracted.get(key, {}).get("status") != "extracted"]
        if missing: review_reasons.append("Required source fields are missing or ambiguous: " + ", ".join(missing))
        doc = VendorSourceDocument(
            import_batch_id=batch.id, source_filename=filename[:255], source_sha256=digest,
            document_type=doc_type, extraction_status=extraction_status,
            mapping_status="review_required", review_required=True,
            review_reasons=review_reasons or ["Import succeeded; compliance evidence still requires review."],
            extracted_fields=extracted, extraction_error=error,
        )
        values = {key: entry.get("value") for key, entry in extracted.items()}
        vendor = None
        name, gstin, address = values.get("vendor_legal_name"), values.get("supplier_gstin"), values.get("vendor_address")
        if extraction_status == "parsed" and name:
            if gstin:
                vendor = db.query(VendorMaster).filter_by(gstin=gstin, is_synthetic=False).first()
            elif address:
                # Conservative fallback: exact normalized name AND address only; never fuzzy-match.
                prior_docs = db.query(VendorSourceDocument).filter(VendorSourceDocument.vendor_id.is_not(None)).all()
                for prior in prior_docs:
                    prior_fields = prior.extracted_fields or {}
                    prior_name = (prior_fields.get("vendor_legal_name") or {}).get("value")
                    prior_address = (prior_fields.get("vendor_address") or {}).get("value")
                    if (prior_name or "").strip().casefold() == name.strip().casefold() and (prior_address or "").strip().casefold() == address.strip().casefold():
                        vendor = db.query(VendorMaster).filter_by(id=prior.vendor_id, is_synthetic=False).first()
                        if vendor:
                            break
            if vendor is None:
                address_text = (address or "").casefold()
                foreign = "usa" in address_text or "united states" in address_text or "united kingdom" in address_text
                country = "US" if "usa" in address_text or "united states" in address_text else "GB" if "united kingdom" in address_text else "IN"
                vendor_code = f"HR-{gstin}" if gstin else f"HR-DOC-{digest[:12].upper()}"
                vendor = VendorMaster(
                    vendor_code=vendor_code, legal_name=name[:255], gstin=gstin,
                    pan=values.get("supplier_pan"), state_code=values.get("vendor_state_code"),
                    is_pan_verified=False, is_gstin_verified=False, gstin_status="UNVERIFIED",
                    vendor_type="foreign" if foreign else "domestic", country=country,
                    msme_type=values.get("msme_type") or "unknown", udyam_number=values.get("udyam_number"),
                    is_msme_verified=False, is_synthetic=False,
                )
                db.add(vendor)
                db.flush()
            doc.vendor_id = vendor.id
            if not gstin:
                doc.review_reasons.append("Supplier GSTIN was not extracted; vendor identity uses a source-specific provisional record or exact name-and-address match and requires review.")
        if extraction_status == "parsed" and doc_type == "tax_invoice":
            
            complete = all(extracted.get(k, {}).get("status") == "extracted" for k in required)
            state_supplier, state_pos = values.get("vendor_state_code"), values.get("place_of_supply_state_code")
            if vendor and complete and state_supplier and state_pos:
                prior = db.query(VendorInvoice).filter_by(vendor_id=vendor.id, invoice_number=values["invoice_number"]).first()
                if prior:
                    doc.invoice_id = prior.id
                    doc.mapping_status = "duplicate_invoice_identity"
                    doc.review_reasons = ["An invoice with this vendor GSTIN and invoice number already exists; linked without creating a duplicate."]
                elif values.get("currency") == "INR":
                    components = [values.get("cgst_amount"), values.get("sgst_amount"), values.get("igst_amount"), values.get("cess_amount")]
                    tax_total = (Decimal(values["explicit_total_tax"]) if values.get("explicit_total_tax") is not None
                                 else sum((Decimal(x) for x in components), Decimal("0")) if all(x is not None for x in components)
                                 else None)
                    invoice = VendorInvoice(
                        vendor_id=vendor.id, invoice_number=values["invoice_number"][:100],
                        invoice_date=date.fromisoformat(values["invoice_date"]),
                        financial_year=f"{date.fromisoformat(values['invoice_date']).year}-{str(date.fromisoformat(values['invoice_date']).year + 1)[-2:]}",
                        supply_type="intra_state" if state_supplier == state_pos else "inter_state",
                        pos_state_code=state_pos, recipient_state_code=state_pos,
                        is_rcm=(values.get("reverse_charge") or "").casefold() in ("yes", "applicable"),
                        taxable_amount=Decimal(values["taxable_value"]),
                        cgst_amount=Decimal(components[0]) if components[0] is not None else None,
                        sgst_amount=Decimal(components[1]) if components[1] is not None else None,
                        igst_amount=Decimal(components[2]) if components[2] is not None else None,
                        total_tax_amount=tax_total, total_amount=Decimal(values["total_invoice_value"]),
                        currency="INR", tds_section=None, is_synthetic=False,
                    )
                    db.add(invoice)
                    db.flush()
                    doc.invoice_id = invoice.id
                    doc.mapping_status = "mapped"
                    doc.review_required = True
                    doc.review_reasons = ["Invoice mapped from document; statutory registration, GSTR-2B, payment, TDS and MSME evidence remain unverified."]
                else:
                    doc.mapping_status = "review_required"
                    doc.review_reasons.append("Non-INR invoice was not mapped to the INR-only existing compliance model.")
        try:
            from pathlib import Path
            storage_dir = Path(__file__).resolve().parents[3] / "data" / "uploads" / "vendor_documents"
            storage_dir.mkdir(parents=True, exist_ok=True)
            storage_path = storage_dir / f"{digest}.pdf"
            if not storage_path.exists():
                storage_path.write_bytes(data)
            doc.storage_key = f"vendor_documents/{digest}.pdf"
        except OSError:
            doc.extraction_error = doc.extraction_error or "Source PDF storage unavailable; extracted metadata retained."
        db.add(doc)
        batch.parsed_files += extraction_status == "parsed"
        batch.failed_files += extraction_status == "failed"
        batch.review_required_files += bool(doc.review_required)
        results.append({"filename": filename, "status": extraction_status, "document_id": doc.id,
                        "document_type": doc_type, "review_required": True,
                        "review_reasons": doc.review_reasons})
    db.commit()
    return {"batch_id": batch.id, "total_files": batch.total_files, "parsed_files": batch.parsed_files,
            "failed_files": batch.failed_files, "duplicate_files": batch.duplicate_files,
            "review_required_files": batch.review_required_files, "documents": results,
            "notice": "Invoice text extraction is not tax verification; external records and approved rules are required."}
