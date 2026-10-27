import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class Customer(UUIDPKMixin, TimestampMixin, Base):
    """A wholesale customer. Added once by an admin; orders link to them so the
    system knows their delivery zone (enables AI auto-assignment).

    Credit terms live here too: a limit on what they may owe, how many days
    they have to pay, and a manual hold that stops new orders going through
    without approval. NULL limit/terms fall back to the business defaults.
    A customer with a VAT or CR number gets standard (B2B) e-invoices, which
    ZATCA clears; everyone else gets simplified ones, which are reported.
    """

    __tablename__ = "customers"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    whatsapp_number: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    # accounts and credit (see app.modules.accounts)
    vat_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    payment_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    on_hold: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    # e-invoicing: B2B (standard) invoices need the buyer's national address and an ID
    cr_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    street: Mapped[str | None] = mapped_column(String(255), nullable=True)
    building_number: Mapped[str | None] = mapped_column(String(8), nullable=True)
    district: Mapped[str | None] = mapped_column(String(127), nullable=True)
    city: Mapped[str | None] = mapped_column(String(127), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(10), nullable=True)