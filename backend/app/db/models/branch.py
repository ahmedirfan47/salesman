import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class Branch(UUIDPKMixin, TimestampMixin, Base):
    """A branch of the business: its own stock, price list, zones, staff and
    WhatsApp number. Every tenant has exactly one default branch, which picks
    up anything that isn't tied to a branch yet.
    """

    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_branch_tenant_name"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # WhatsApp Cloud API number for this branch (Meta "phone number ID").
    whatsapp_phone_number_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    whatsapp_access_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    whatsapp_display_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Meta-approved template used for order updates outside the 24-hour window.
    whatsapp_update_template: Mapped[str | None] = mapped_column(String(120), nullable=True)
    order_updates_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)