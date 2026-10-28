"""Connections to accounting systems / ERPs (Odoo first; Zoho Books, Qoyod and SAP Business One next).

- IntegrationConnection: one per business. Credentials (sealed), the mapping
  of branches to warehouses and price lists, taxes and journals, and what to
  sync.
- IntegrationLink: which record in the ERP a Salesman record became, so
  nothing is ever created twice.
- IntegrationEvent: one line per thing sent or fetched, with its outcome --
  what the activity list and the "needs attention" list show.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class IntegrationConnection(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "integration_connections"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_integration_connection_tenant"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)          # odoo | zoho_books | qoyod | sap_b1
    # draft (credentials saved, mapping not finished) | active | paused
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    database: Mapped[str | None] = mapped_column(String(120), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    secret: Mapped[str] = mapped_column(Text, nullable=False)                  # sealed API key
    api: Mapped[str | None] = mapped_column(String(16), nullable=True)         # json2 | jsonrpc
    server_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_pull_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_pull_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class IntegrationLink(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "integration_links"
    __table_args__ = (
        UniqueConstraint("connection_id", "entity", "local_key", name="uq_integration_link_local"),
        Index("ix_integration_links_external", "connection_id", "entity", "external_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False
    )
    # customer | walkin | product | order | invoice | credit_note | payment | allocation
    entity: Mapped[str] = mapped_column(String(20), nullable=False)
    local_key: Mapped[str] = mapped_column(String(80), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)  # e.g. INV/2026/00012
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class IntegrationEvent(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "integration_events"
    __table_args__ = (
        UniqueConstraint("connection_id", "action", "local_key", name="uq_integration_event_item"),
        Index("ix_integration_events_recent", "connection_id", "updated_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(8), nullable=False)          # push | pull
    # order.confirmed | order.delivered | order.cancelled | invoice | payment | payment.void | customer | catalog
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    local_key: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)            # e.g. INV-000123, "Prices and stock"
    status: Mapped[str] = mapped_column(String(12), nullable=False)            # pending | ok | warning | failed | skipped
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )