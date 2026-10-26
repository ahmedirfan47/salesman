import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class Prospect(UUIDPKMixin, TimestampMixin, Base):
    """A shop the sales team wants to win: a new one, or a customer who went quiet.

    kind:   'new'     -- not a customer yet (manual, imported, or from Google Maps)
            'winback' -- an existing customer ordering far less often than usual
    status: new -> contacted -> interested -> won | lost
    """

    __tablename__ = "prospects"
    __table_args__ = (
        # Google may only be relied on for the place ID long-term, so it is the
        # dedupe key for Google-sourced prospects (NULLs are allowed many times).
        UniqueConstraint("tenant_id", "google_place_id", name="uq_prospect_tenant_place"),
        Index("ix_prospects_tenant_status", "tenant_id", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="SET NULL"), index=True, nullable=True
    )
    kind: Mapped[str] = mapped_column(String(16), default="new", nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)  # manual|import|google|winback
    status: Mapped[str] = mapped_column(String(16), default="new", nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Normalised to +<country><number> so it matches customers and builds wa.me links.
    phone: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    area: Mapped[str | None] = mapped_column(String(120), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zones.id", ondelete="SET NULL"), index=True, nullable=True
    )

    google_place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_maps_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Why this prospect is worth a call, e.g. "Usually orders every 5 days; last order 26 days ago".
    insight: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    lost_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # win-back: the existing customer; new prospect: the customer it became when won
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), index=True, nullable=True
    )

    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProspectActivity(UUIDPKMixin, TimestampMixin, Base):
    """Timeline entry on a prospect: created, note, contacted, status change, won."""

    __tablename__ = "prospect_activities"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    prospect_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prospects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # created|note|contacted|status|won
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)