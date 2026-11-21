import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class ReorderNudge(UUIDPKMixin, TimestampMixin, Base):
    """A WhatsApp message offering a customer their usual order, sent when they
    are later than usual to reorder (see app.modules.reorder.service).

    One per customer per "last order": a customer who doesn't reorder is
    nudged once, not every day. `converted_order_id` is the first order the
    customer placed within the attribution window after the nudge.
    status: queued | sent | failed | skipped
    """

    __tablename__ = "reorder_nudges"
    __table_args__ = (UniqueConstraint("tenant_id", "customer_id", "last_order_id", name="uq_reorder_nudge"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    last_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    typical_days: Mapped[int] = mapped_column(nullable=False)
    suggested: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    converted_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
