"""ZATCA e-invoicing (Fatoora, Phase 2).

- ZatcaUnit: one e-invoicing device (EGS unit) per branch. It holds the
  branch's private key, its ZATCA certificates and secrets (encrypted), and
  the hash chain: the invoice counter (ICV) and the hash of the last document
  it signed (the next document's PIH).
- ZatcaDocument: one signed XML for a tax invoice or credit note, and what
  ZATCA said about it. Standard (B2B) documents are cleared before they count;
  simplified (B2C) ones are reported within 24 hours. A rejected document is
  never edited: it is superseded by a corrected one with a new ICV and UUID.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class ZatcaUnit(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "zatca_units"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    # sandbox (developer portal) | simulation | production
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    # draft -> active ; failed when onboarding stopped ; disabled when switched off
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    common_name: Mapped[str] = mapped_column(String(64), nullable=False)
    egs_serial: Mapped[str] = mapped_column(String(128), nullable=False)
    organization_unit: Mapped[str] = mapped_column(String(64), nullable=False)
    # "1100" standard + simplified, "1000" standard only, "0100" simplified only
    invoice_types: Mapped[str] = mapped_column(String(4), default="1100", nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str] = mapped_column(String(120), nullable=False)

    private_key: Mapped[str] = mapped_column(Text, nullable=False)          # encrypted PEM
    csr: Mapped[str] = mapped_column(Text, nullable=False)                  # PEM
    compliance_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    compliance_secret: Mapped[str | None] = mapped_column(Text, nullable=True)   # encrypted
    compliance_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # [{"label": "Simplified invoice", "status": "PASS", "errors": [...], "warnings": [...]}]
    compliance_results: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    production_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    production_secret: Mapped[str | None] = mapped_column(Text, nullable=True)   # encrypted
    certificate: Mapped[str | None] = mapped_column(Text, nullable=True)         # base64 DER body
    certificate_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # the hash chain; the row is locked while a document is signed
    icv: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ZatcaDocument(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "zatca_documents"
    __table_args__ = (
        Index("ix_zatca_documents_tenant_status", "tenant_id", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), index=True, nullable=False
    )
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zatca_units.id", ondelete="SET NULL"), nullable=True
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_invoices.id"), index=True, nullable=False
    )
    # standard (B2B, cleared) | simplified (B2C, reported)
    flow: Mapped[str] = mapped_column(String(16), nullable=False)
    # invoice | credit_note
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # blocked (data missing, not signed) | queued | cleared | reported | rejected | superseded
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    icv: Mapped[int | None] = mapped_column(Integer, nullable=True)
    document_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    invoice_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pih: Mapped[str | None] = mapped_column(String(128), nullable=True)
    xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr: Mapped[str | None] = mapped_column(Text, nullable=True)
    # standard invoices: the XML ZATCA returns, stamped -- this is the legal invoice
    cleared_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # CLEARED / NOT_CLEARED / REPORTED / NOT_REPORTED as ZATCA said it
    zatca_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # [{"code": ..., "message": ...}]
    errors: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    warnings: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zatca_documents.id"), nullable=True
    )