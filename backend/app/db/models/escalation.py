import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class Escalation(UUIDPKMixin, TimestampMixin, Base):
    """A situation the AI must not decide alone -> routed to a human admin.

    Foundation of the whole human-escalation system. For now it's created by
    the orders module when stock is insufficient; later the WhatsApp layer
    reads open escalations to notify admins and post resolutions back.
    """

    __tablename__ = "escalations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # e.g. insufficient_stock | special_price | dispute | unverifiable | payment | delivery
    reason_type: Mapped[str] = mapped_column(String(40), nullable=False)
    context: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    ai_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)

    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    whatsapp_number: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # open -> resolved  (resolution: approved | rejected)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)