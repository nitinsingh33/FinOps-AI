"""Add source-traceable vendor PDF import records and nullable tax evidence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261024_vendor_pdf_docs"
down_revision = "91ac47bbd032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("vendor_invoices", "cgst_amount", existing_type=sa.Numeric(20, 6), nullable=True)
    op.alter_column("vendor_invoices", "sgst_amount", existing_type=sa.Numeric(20, 6), nullable=True)
    op.alter_column("vendor_invoices", "igst_amount", existing_type=sa.Numeric(20, 6), nullable=True)
    op.alter_column("vendor_invoices", "total_tax_amount", existing_type=sa.Numeric(20, 6), nullable=True)
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "vendor_document_import_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_name", sa.String(100), nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("total_files", sa.Integer(), nullable=False),
        sa.Column("parsed_files", sa.Integer(), nullable=False),
        sa.Column("failed_files", sa.Integer(), nullable=False),
        sa.Column("duplicate_files", sa.Integer(), nullable=False),
        sa.Column("review_required_files", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_vendor_doc_batches_created", "vendor_document_import_batches", ["created_at"])
    op.create_table(
        "vendor_source_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("import_batch_id", sa.String(36), sa.ForeignKey("vendor_document_import_batches.id"), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("storage_key", sa.String(255), nullable=True),
        sa.Column("source_dataset", sa.String(100), nullable=False),
        sa.Column("document_type", sa.String(30), nullable=False),
        sa.Column("extraction_status", sa.String(30), nullable=False),
        sa.Column("mapping_status", sa.String(30), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("review_reasons", json_type, nullable=False),
        sa.Column("extracted_fields", json_type, nullable=False),
        sa.Column("extraction_error", sa.String(255), nullable=True),
        sa.Column("vendor_id", sa.String(36), sa.ForeignKey("vendor_masters.id"), nullable=True),
        sa.Column("invoice_id", sa.String(36), sa.ForeignKey("vendor_invoices.id"), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_vendor_source_docs_vendor", "vendor_source_documents", ["vendor_id"])
    op.create_index("ix_vendor_source_docs_invoice", "vendor_source_documents", ["invoice_id"])
    op.create_index("ix_vendor_source_docs_batch", "vendor_source_documents", ["import_batch_id"])
    op.create_index("ix_vendor_source_docs_dataset", "vendor_source_documents", ["source_dataset"])


def downgrade() -> None:
    op.drop_table("vendor_source_documents")
    op.drop_table("vendor_document_import_batches")
    op.alter_column("vendor_invoices", "cgst_amount", existing_type=sa.Numeric(20, 6), nullable=False)
    op.alter_column("vendor_invoices", "sgst_amount", existing_type=sa.Numeric(20, 6), nullable=False)
    op.alter_column("vendor_invoices", "igst_amount", existing_type=sa.Numeric(20, 6), nullable=False)
    op.alter_column("vendor_invoices", "total_tax_amount", existing_type=sa.Numeric(20, 6), nullable=False)
