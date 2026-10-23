"""
Vendor Compliance Data Models: GST, TDS, MSME, and Master Data Integrity.

Design rules:
- UUID primary keys
- Decimal(20, 6) for financial calculations
- Dialect-agnostic JSON (PostgreSQL JSONB + SQLite JSON)
- Explicit provenance and synthetic flags
- Versioned Tax Rules table
"""
from __future__ import annotations

import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    JSON,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

json_type = JSON().with_variant(JSONB, "postgresql")


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ComplianceStatus:
    COMPLIANT = "compliant"
    NEEDS_ATTENTION = "needs_attention"
    HIGH_RISK = "high_risk"


class ExceptionCategoryType:
    GST = "gst"
    TDS = "tds"
    MSME = "msme"
    MASTER_DATA = "master_data"


class SeverityLevel:
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaxCategory:
    TDS = "tds"
    GST = "gst"


class RuleApprovalStatus:
    APPROVED = "approved"
    PENDING_REVIEW = "pending_review"
    DRAFT = "draft"
    DEPRECATED = "deprecated"


# ---------------------------------------------------------------------------
# Tax Rules Table (Income-tax Act 1961 vs 2025 Mappings & GST Rules)
# ---------------------------------------------------------------------------

class TaxRule(Base):
    """
    Versioned repository of GST and TDS compliance rules.
    Maintains statutory references under both Income-tax Act, 1961 and 2025.
    Requires explicit tax-team approval before treating as active law.
    """
    __tablename__ = "tax_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    rule_code: Mapped[str] = mapped_column(String(50), nullable=False)
    tax_category: Mapped[str] = mapped_column(String(20), nullable=False)  # 'tds' or 'gst'
    section_1961: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g. "194C"
    section_2025: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g. "Clause 212 / ITA 2025"
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    rate_pct: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    threshold_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal("0.00"))
    tax_base: Mapped[str] = mapped_column(String(50), nullable=False, default="EXCLUDE_GST")  # EXCLUDE_GST, GROSS, NET
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    applicability_conditions: Mapped[Optional[Dict[str, Any]]] = mapped_column(json_type, nullable=True)
    source_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=RuleApprovalStatus.PENDING_REVIEW
    )
    approved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    is_sample_rule: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("rule_code", "version", name="uq_tax_rule_code_version"),
        Index("ix_tax_rules_category", "tax_category"),
        Index("ix_tax_rules_code", "rule_code"),
    )


# ---------------------------------------------------------------------------
# Vendor Master
# ---------------------------------------------------------------------------

class VendorMaster(Base):
    """
    Vendor Master record including PAN, GSTIN, MSME Udyam credentials, and payment terms.
    Explicitly tracks synthetic provenance and authoritative verification status.
    """
    __tablename__ = "vendor_masters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    vendor_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    trade_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pan: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_pan_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pan_operative_status: Mapped[str] = mapped_column(String(20), default="OPERATIVE", nullable=False)  # OPERATIVE, INOPERATIVE
    gstin: Mapped[Optional[str]] = mapped_column(String(25), nullable=True)
    is_gstin_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    gstin_status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)  # ACTIVE, INACTIVE, CANCELLED
    state_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # First 2 digits of GSTIN e.g. "27"
    vendor_type: Mapped[str] = mapped_column(String(30), default="domestic", nullable=False)  # domestic, foreign
    country: Mapped[str] = mapped_column(String(10), default="IN", nullable=False)
    msme_type: Mapped[str] = mapped_column(String(30), default="non_msme", nullable=False)  # micro, small, medium, non_msme
    udyam_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Format UDYAM-XX-00-0000000
    is_msme_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    bank_account_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    bank_ifsc: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    invoices: Mapped[List["VendorInvoice"]] = relationship("VendorInvoice", back_populates="vendor")
    payments: Mapped[List["VendorPayment"]] = relationship("VendorPayment", back_populates="vendor")
    scorecard: Mapped[Optional["VendorScorecard"]] = relationship("VendorScorecard", back_populates="vendor", uselist=False)

    __table_args__ = (
        Index("ix_vendor_masters_pan", "pan"),
        Index("ix_vendor_masters_gstin", "gstin"),
        Index("ix_vendor_masters_msme", "msme_type"),
    )


# ---------------------------------------------------------------------------
# Invoices & Invoice Line Items
# ---------------------------------------------------------------------------

class VendorInvoice(Base):
    """
    Vendor invoice header and tax details.
    """
    __tablename__ = "vendor_invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendor_masters.id"), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    financial_year: Mapped[str] = mapped_column(String(20), nullable=False, default="2025-26")
    supply_type: Mapped[str] = mapped_column(String(30), nullable=False, default="intra_state")  # intra_state (CGST+SGST), inter_state (IGST)
    pos_state_code: Mapped[str] = mapped_column(String(10), nullable=False, default="27")
    recipient_state_code: Mapped[str] = mapped_column(String(10), nullable=False, default="27")
    hsn_sac_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_rcm: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_blocked_itc_17_5: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    blocked_itc_category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # motor_vehicle, food_beverage, personal_consumption
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal("0.00"), nullable=False)
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal("0.00"), nullable=False)
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal("0.00"), nullable=False)
    total_tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    tds_section: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g. "194C", "194J", "195"
    tds_rate_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    tds_base_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    tds_deducted_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal("0.00"), nullable=False)
    acceptance_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_disputed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dispute_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    has_form_15ca_15cb: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # For foreign vendors
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    vendor: Mapped["VendorMaster"] = relationship("VendorMaster", back_populates="invoices")
    payments: Mapped[List["VendorPayment"]] = relationship("VendorPayment", back_populates="invoice")

    __table_args__ = (
        UniqueConstraint("vendor_id", "invoice_number", name="uq_vendor_invoice_no"),
        Index("ix_vendor_invoices_date", "invoice_date"),
        Index("ix_vendor_invoices_tds_section", "tds_section"),
    )


# ---------------------------------------------------------------------------
# Vendor Payments
# ---------------------------------------------------------------------------

class VendorPayment(Base):
    """
    Payment made against a vendor invoice.
    Tracks payment date for MSME 45-day calculation and 180-day ITC rule.
    """
    __tablename__ = "vendor_payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendor_masters.id"), nullable=False)
    invoice_id: Mapped[Optional[str]] = mapped_column(ForeignKey("vendor_invoices.id"), nullable=True)
    payment_reference: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    gross_amount_paid: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    tds_deducted_at_payment: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal("0.00"), nullable=False)
    net_amount_paid: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    bank_reference_utr: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    vendor: Mapped["VendorMaster"] = relationship("VendorMaster", back_populates="payments")
    invoice: Mapped[Optional["VendorInvoice"]] = relationship("VendorInvoice", back_populates="payments")

    __table_args__ = (
        Index("ix_vendor_payments_date", "payment_date"),
        Index("ix_vendor_payments_vendor", "vendor_id"),
    )


# ---------------------------------------------------------------------------
# GSTR-2B Records (Government Auto-Drafted ITC Statement)
# ---------------------------------------------------------------------------

class GSTR2BRecord(Base):
    """
    Record from imported GSTR-2B statement.
    Used for 3-way matching with internal VendorInvoices.
    """
    __tablename__ = "gstr_2b_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    gstin_supplier: Mapped[str] = mapped_column(String(25), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    invoice_type: Mapped[str] = mapped_column(String(20), default="Regular", nullable=False)
    taxable_value: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    igst: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal("0.00"), nullable=False)
    cgst: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal("0.00"), nullable=False)
    sgst: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal("0.00"), nullable=False)
    itc_availability: Mapped[str] = mapped_column(String(10), default="Y", nullable=False)  # Y or N
    return_period: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "092025"
    filing_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("gstin_supplier", "invoice_number", "return_period", name="uq_gstr2b_invoice"),
        Index("ix_gstr2b_supplier", "gstin_supplier"),
        Index("ix_gstr2b_invoice_no", "invoice_number"),
    )


# ---------------------------------------------------------------------------
# TDS Challans (ITNS 281 Government Deposit Records)
# ---------------------------------------------------------------------------

class TDSChallan(Base):
    """
    TDS Tax Deposit Challan (ITNS 281).
    Used to reconcile TDS deducted against TDS deposited with Government.
    """
    __tablename__ = "tds_challans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    challan_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    bsr_code: Mapped[str] = mapped_column(String(20), nullable=False)
    deposit_date: Mapped[date] = mapped_column(Date, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    interest_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0.00"), nullable=False)
    fee_penalty_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0.00"), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    financial_year: Mapped[str] = mapped_column(String(20), default="2025-26", nullable=False)
    quarter: Mapped[str] = mapped_column(String(10), nullable=False)  # Q1, Q2, Q3, Q4
    section_code: Mapped[str] = mapped_column(String(50), nullable=False)  # 194C, 194J, 194I, 195
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_tds_challan_deposit_date", "deposit_date"),
        Index("ix_tds_challan_section", "section_code"),
    )


# ---------------------------------------------------------------------------
# TDS Quarterly Returns (Form 26Q / 27Q Reported Records)
# ---------------------------------------------------------------------------

class TDSReturnRecord(Base):
    """
    Form 26Q (domestic) or Form 27Q (non-resident) line item reported to IT Dept.
    Used for 3-way TDS reconciliation: Deducted vs Deposited vs Reported.
    """
    __tablename__ = "tds_return_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    form_type: Mapped[str] = mapped_column(String(10), default="26Q", nullable=False)  # 26Q, 27Q
    quarter: Mapped[str] = mapped_column(String(10), nullable=False)  # Q1, Q2, Q3, Q4
    financial_year: Mapped[str] = mapped_column(String(20), default="2025-26", nullable=False)
    deductee_pan: Mapped[str] = mapped_column(String(20), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    section_code: Mapped[str] = mapped_column(String(50), nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    tax_deducted: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    tax_deposited: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    challan_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_tds_returns_pan", "deductee_pan"),
        Index("ix_tds_returns_invoice", "invoice_number"),
    )


# ---------------------------------------------------------------------------
# Compliance Exceptions
# ---------------------------------------------------------------------------

class VendorComplianceException(Base):
    """
    Granular exception raised by GST, TDS, MSME, or Master Data checks.
    Includes amount at stake, evidence breakdown, rule version, and human review status.
    """
    __tablename__ = "vendor_compliance_exceptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    check_code: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "GST_GSTR2B_MISSING", "MSME_45_DAY_BREACH"
    category: Mapped[str] = mapped_column(String(30), nullable=False)  # gst, tds, msme, master_data
    severity: Mapped[str] = mapped_column(String(20), default=SeverityLevel.MEDIUM, nullable=False)  # high, medium, low
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendor_masters.id"), nullable=False)
    invoice_id: Mapped[Optional[str]] = mapped_column(ForeignKey("vendor_invoices.id"), nullable=True)
    rule_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    rule_version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount_at_stake: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    calculation_breakdown: Mapped[Optional[Dict[str, Any]]] = mapped_column(json_type, nullable=True)
    evidence: Mapped[Optional[Dict[str, Any]]] = mapped_column(json_type, nullable=True)
    missing_information: Mapped[Optional[List[str]]] = mapped_column(json_type, nullable=True)
    suggested_action: Mapped[str] = mapped_column(Text, nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)  # open, in_review, resolved, waived
    analyst_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_synthetic_warning: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    vendor: Mapped["VendorMaster"] = relationship("VendorMaster")
    invoice: Mapped[Optional["VendorInvoice"]] = relationship("VendorInvoice")

    __table_args__ = (
        Index("ix_vce_category", "category"),
        Index("ix_vce_severity", "severity"),
        Index("ix_vce_vendor_id", "vendor_id"),
        Index("ix_vce_review_status", "review_status"),
    )


# ---------------------------------------------------------------------------
# Vendor Scorecard
# ---------------------------------------------------------------------------

class VendorScorecard(Base):
    """
    Vendor-level synthesized risk scorecard.
    Statuses: Compliant, Needs Attention, High Risk.
    Transparent explainability: lists each failed or unverified check.
    """
    __tablename__ = "vendor_scorecards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendor_masters.id"), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)  # compliant, needs_attention, high_risk
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0 to 100
    gst_status: Mapped[str] = mapped_column(String(30), default="compliant", nullable=False)
    tds_status: Mapped[str] = mapped_column(String(30), default="compliant", nullable=False)
    msme_status: Mapped[str] = mapped_column(String(30), default="compliant", nullable=False)
    master_data_status: Mapped[str] = mapped_column(String(30), default="compliant", nullable=False)
    total_amount_at_stake: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0.00"), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    summary_reasons: Mapped[List[str]] = mapped_column(json_type, default=list, nullable=False)
    evidence_coverage: Mapped[Dict[str, Any]] = mapped_column(json_type, default=dict, nullable=False)
    recommended_actions: Mapped[List[str]] = mapped_column(json_type, default=list, nullable=False)
    last_assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    vendor: Mapped["VendorMaster"] = relationship("VendorMaster", back_populates="scorecard")


# ---------------------------------------------------------------------------
# Vendor Master Cleanup Items
# ---------------------------------------------------------------------------

class VendorMasterCleanupItem(Base):
    """
    Data quality anomalies detected in vendor master records:
    Malformed PAN/GSTIN, PAN-GSTIN mismatch, duplicate vendor candidates, missing MSME registration.
    """
    __tablename__ = "vendor_master_cleanup_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendor_masters.id"), nullable=False)
    issue_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default=SeverityLevel.MEDIUM, nullable=False)
    field_name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    duplicate_candidate_vendor_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("vendor_masters.id"), nullable=True
    )
    is_verified_mismatch: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recommended_fix: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)  # open, resolved, ignored
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    vendor: Mapped["VendorMaster"] = relationship("VendorMaster", foreign_keys=[vendor_id])
    duplicate_candidate: Mapped[Optional["VendorMaster"]] = relationship(
        "VendorMaster", foreign_keys=[duplicate_candidate_vendor_id]
    )

    __table_args__ = (
        Index("ix_vmc_vendor_id", "vendor_id"),
        Index("ix_vmc_issue_type", "issue_type"),
    )
