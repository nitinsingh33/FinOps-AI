"""
SQLAlchemy ORM models for FinOps AI.

Design principles:
- UUID primary keys for all entities
- Explicit currency fields alongside every monetary column
- Decimal(20, 6) for monetary values — rounded only at documented boundaries
- JSONB for gateway-specific metadata that doesn't need relational querying
- Provenance links: every normalized record traces back to its source_record
- Audit timestamps on every table
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enumerations (stored as strings for readability and forward-compat)
# ---------------------------------------------------------------------------

class GatewayName:
    GATEWAY_A = "gateway_a"
    GATEWAY_B = "gateway_b"

class DatasetType:
    GWA_PAYMENTS = "gwa_payments"
    GWA_TRANSACTIONS = "gwa_transactions"
    GWA_REFUNDS = "gwa_refunds"
    GWB_BALANCE = "gwb_balance"

class ImportStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"

class ReconciliationStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class MatchMethod:
    EXACT_ID = "exact_id"
    ORDER_ID = "order_id"
    SETTLEMENT_ID = "settlement_id"
    AMOUNT_CURRENCY_DATE = "amount_currency_date"
    MANUAL = "manual"

class MatchConfidence:
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    AMBIGUOUS = "ambiguous"

class ExceptionCategory:
    MISSING_GATEWAY_TXN = "missing_gateway_txn"
    MISSING_PAYMENT = "missing_payment"
    UNMATCHED_REFUND = "unmatched_refund"
    REFUND_AMOUNT_MISMATCH = "refund_amount_mismatch"
    FEE_DISCREPANCY = "fee_discrepancy"
    TAX_DISCREPANCY = "tax_discrepancy"
    NET_AMOUNT_MISMATCH = "net_amount_mismatch"
    MISSING_SETTLEMENT = "missing_settlement"
    UNSETTLED_TRANSACTION = "unsettled_transaction"
    SETTLEMENT_DELAY = "settlement_delay"
    DUPLICATE_RECORD = "duplicate_record"
    INVALID_DATA = "invalid_data"
    AMBIGUOUS_MATCH = "ambiguous_match"
    CURRENCY_MISMATCH = "currency_mismatch"

class ReviewStatus:
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


# ---------------------------------------------------------------------------
# Upload and Import models
# ---------------------------------------------------------------------------

class UploadedDataset(Base):
    __tablename__ = "uploaded_datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    dataset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    gateway: Mapped[str] = mapped_column(String(50), nullable=False)
    file_hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=True)
    upload_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    import_jobs: Mapped[list["ImportJob"]] = relationship("ImportJob", back_populates="dataset")

    __table_args__ = (
        UniqueConstraint("file_hash_sha256", "dataset_type", name="uq_dataset_hash_type"),
        Index("ix_uploaded_datasets_gateway", "gateway"),
        Index("ix_uploaded_datasets_dataset_type", "dataset_type"),
    )


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("uploaded_datasets.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=ImportStatus.QUEUED)
    total_rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    processed_rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    imported_rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    skipped_rows: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    warning_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duplicate_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    dataset: Mapped["UploadedDataset"] = relationship("UploadedDataset", back_populates="import_jobs")
    row_errors: Mapped[list["ImportRowError"]] = relationship("ImportRowError", back_populates="job")

    __table_args__ = (
        Index("ix_import_jobs_status", "status"),
        Index("ix_import_jobs_dataset_id", "dataset_id"),
    )


class ImportRowError(Base):
    __tablename__ = "import_row_errors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("import_jobs.id"), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="warning")
    field_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    raw_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped["ImportJob"] = relationship("ImportJob", back_populates="row_errors")

    __table_args__ = (Index("ix_import_row_errors_job_id", "job_id"),)


# ---------------------------------------------------------------------------
# Normalized financial records
# ---------------------------------------------------------------------------

class SourceRecord(Base):
    """
    Immutable raw record as parsed from the source file.
    One row per source file row. Provides provenance for all derived records.
    """
    __tablename__ = "source_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("uploaded_datasets.id"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("import_jobs.id"), nullable=False)
    gateway: Mapped[str] = mapped_column(String(50), nullable=False)
    dataset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_identifier: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    import_warnings: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("gateway", "dataset_type", "source_identifier", name="uq_source_record_identity"),
        Index("ix_source_records_gateway", "gateway"),
        Index("ix_source_records_dataset_type", "dataset_type"),
        Index("ix_source_records_source_identifier", "source_identifier"),
        Index("ix_source_records_dataset_id", "dataset_id"),
    )


class Payment(Base):
    """Normalized payment record — one per payment attempt."""
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    source_record_id: Mapped[str] = mapped_column(ForeignKey("source_records.id"), nullable=False)
    gateway: Mapped[str] = mapped_column(String(50), nullable=False)
    gateway_payment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    gateway_order_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Amounts — use Decimal(20,6) for precision; currency stored alongside
    gross_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    fee_currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    tax: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    tax_currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    amount_refunded: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    is_international: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_captured: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    card_network: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    card_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    transacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    gateway_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("gateway", "gateway_payment_id", name="uq_payment_gateway_id"),
        Index("ix_payments_gateway", "gateway"),
        Index("ix_payments_status", "status"),
        Index("ix_payments_currency", "currency"),
        Index("ix_payments_transacted_at", "transacted_at"),
        Index("ix_payments_gateway_order_id", "gateway_order_id"),
    )


class GatewayTransaction(Base):
    """
    Ledger/transaction record from gateway.
    Gateway A exports a separate transactions file; Gateway B uses balance_transactions.
    """
    __tablename__ = "gateway_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    source_record_id: Mapped[str] = mapped_column(ForeignKey("source_records.id"), nullable=False)
    gateway: Mapped[str] = mapped_column(String(50), nullable=False)
    gateway_txn_id: Mapped[str] = mapped_column(String(255), nullable=False)
    txn_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reporting_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Links
    gateway_payment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gateway_order_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    settlement_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    settlement_utr: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Amounts
    gross_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    debit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    credit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    tax: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    net_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    # Customer-facing (GatewayB cross-currency)
    customer_facing_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    customer_facing_currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    # Geography
    country: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    card_network: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    card_brand: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    card_funding: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Settlement
    is_settled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    payout_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Timestamps
    transacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    available_on: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    gateway_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("gateway", "gateway_txn_id", name="uq_gw_txn_gateway_id"),
        Index("ix_gw_txn_gateway", "gateway"),
        Index("ix_gw_txn_type", "txn_type"),
        Index("ix_gw_txn_currency", "currency"),
        Index("ix_gw_txn_settlement_id", "settlement_id"),
        Index("ix_gw_txn_gateway_payment_id", "gateway_payment_id"),
        Index("ix_gw_txn_transacted_at", "transacted_at"),
    )


class Refund(Base):
    """Normalized refund record."""
    __tablename__ = "refunds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    source_record_id: Mapped[str] = mapped_column(ForeignKey("source_records.id"), nullable=False)
    gateway: Mapped[str] = mapped_column(String(50), nullable=False)
    gateway_refund_id: Mapped[str] = mapped_column(String(255), nullable=False)
    gateway_payment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    arn: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    refunded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    gateway_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("gateway", "gateway_refund_id", name="uq_refund_gateway_id"),
        Index("ix_refunds_gateway", "gateway"),
        Index("ix_refunds_gateway_payment_id", "gateway_payment_id"),
    )


class Settlement(Base):
    """Gateway settlement/payout record."""
    __tablename__ = "settlements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    gateway: Mapped[str] = mapped_column(String(50), nullable=False)
    gateway_settlement_id: Mapped[str] = mapped_column(String(255), nullable=False)
    settlement_utr: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payout_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gross_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    tax: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    net_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    settled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    available_on: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("gateway", "gateway_settlement_id", name="uq_settlement_gateway_id"),
        Index("ix_settlements_gateway", "gateway"),
    )


# ---------------------------------------------------------------------------
# Reconciliation models
# ---------------------------------------------------------------------------

class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=ReconciliationStatus.PENDING)
    triggered_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dataset_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    rule_version: Mapped[str] = mapped_column(String(50), nullable=False, default="1.0")
    total_records: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    matched_records: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unmatched_records: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ambiguous_records: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    exception_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    matches: Mapped[list["ReconciliationMatch"]] = relationship(
        "ReconciliationMatch", back_populates="run"
    )
    exceptions: Mapped[list["ReconciliationException"]] = relationship(
        "ReconciliationException", back_populates="run"
    )


class ReconciliationMatch(Base):
    __tablename__ = "reconciliation_matches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("reconciliation_runs.id"), nullable=False)
    match_method: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    payment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gateway_txn_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    match_evidence: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    amount_difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped["ReconciliationRun"] = relationship("ReconciliationRun", back_populates="matches")

    __table_args__ = (Index("ix_recon_matches_run_id", "run_id"),)


class ReconciliationException(Base):
    __tablename__ = "reconciliation_exceptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("reconciliation_runs.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    gateway: Mapped[str] = mapped_column(String(50), nullable=False)
    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    amount_at_stake: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    amount_difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    expected_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    observed_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Source record links
    source_payment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_txn_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_refund_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Review workflow
    review_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=ReviewStatus.OPEN
    )
    assigned_to: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    run: Mapped["ReconciliationRun"] = relationship(
        "ReconciliationRun", back_populates="exceptions"
    )
    investigations: Mapped[list["AIInvestigation"]] = relationship(
        "AIInvestigation", back_populates="exception"
    )
    reviews: Mapped[list["ExceptionReview"]] = relationship(
        "ExceptionReview", back_populates="exception"
    )

    __table_args__ = (
        Index("ix_recon_exceptions_run_id", "run_id"),
        Index("ix_recon_exceptions_category", "category"),
        Index("ix_recon_exceptions_review_status", "review_status"),
        Index("ix_recon_exceptions_gateway", "gateway"),
    )


# ---------------------------------------------------------------------------
# Pricing and Scenarios
# ---------------------------------------------------------------------------

class PricingRule(Base):
    __tablename__ = "pricing_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    gateway: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    is_international: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    fee_rate_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)
    fixed_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    fixed_fee_currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    tax_on_fee_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 6), nullable=True)
    min_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    max_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    effective_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_illustrative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_pricing_rules_gateway", "gateway"),)


class SavingsScenario(Base):
    __tablename__ = "savings_scenarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    current_gateway: Mapped[str] = mapped_column(String(50), nullable=False)
    alternative_gateway: Mapped[str] = mapped_column(String(50), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    eligible_volume: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    current_pricing_rule_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("pricing_rules.id"), nullable=True
    )
    alternative_pricing_rule_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("pricing_rules.id"), nullable=True
    )
    current_estimated_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    alternative_estimated_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    estimated_difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 6), nullable=True)
    assumptions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    limitations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# AI and Review
# ---------------------------------------------------------------------------

class AIInvestigation(Base):
    __tablename__ = "ai_investigations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    exception_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_exceptions.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    evidence_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified_facts: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    possible_explanations: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    missing_information: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    recommended_steps: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    confidence_assessment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_response: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="completed")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    exception: Mapped["ReconciliationException"] = relationship(
        "ReconciliationException", back_populates="investigations"
    )

    __table_args__ = (Index("ix_ai_investigations_exception_id", "exception_id"),)


class ExceptionReview(Base):
    __tablename__ = "exception_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    exception_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_exceptions.id"), nullable=False
    )
    reviewer: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(50), nullable=False)
    new_status: Mapped[str] = mapped_column(String(50), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    exception: Mapped["ReconciliationException"] = relationship(
        "ReconciliationException", back_populates="reviews"
    )

    __table_args__ = (Index("ix_exception_reviews_exception_id", "exception_id"),)


class AuditEvent(Base):
    """Append-only audit trail for all financial workflow changes."""
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_event_type", "event_type"),
        Index("ix_audit_events_created_at", "created_at"),
    )
