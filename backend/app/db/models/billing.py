import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, Sequence, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin

# Invoice numbers come from one database sequence, so two invoices issued at
# the same moment can never get the same number.
INVOICE_NUMBER_SEQ = Sequence("invoice_number_seq", metadata=Base.metadata)


class Subscription(UUIDPKMixin, TimestampMixin, Base):
    """What one business pays Stonic: a setup fee and a monthly fee per active branch.

    Set up by Stonic from the admin console. Monthly invoices are issued in
    advance on `next_invoice_on`, then that date moves on by one month.
    """

    __tablename__ = "subscriptions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    # active -> paused (no new invoices) -> active, or cancelled
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    setup_fee_per_branch: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    monthly_fee_per_branch: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    # days after the due date before the account becomes read-only
    grace_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    next_invoice_on: Mapped[date] = mapped_column(Date, nullable=False)
    # branches whose setup fee has been invoiced; new branches beyond this owe setup
    setup_billed_branches: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # the customer's legal details, printed on invoices
    billing_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    billing_tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class Invoice(UUIDPKMixin, TimestampMixin, Base):
    """An invoice from Stonic to a business. Lines and totals never change once issued;
    a wrong invoice is voided and a new one issued."""

    __tablename__ = "invoices"
    __table_args__ = (
        # one live monthly invoice per subscription per period
        Index(
            "uq_invoice_subscription_period", "subscription_id", "period_start", unique=True,
            postgresql_where=text("kind = 'subscription' AND status <> 'void'"),
        ),
        Index("ix_invoices_tenant_status", "tenant_id", "status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # setup | subscription | other
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)  # open | paid | void
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # [{"description", "quantity", "unit_amount", "amount"}], amounts as strings
    lines: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # snapshot of the customer's details at issue time
    bill_to: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    voided_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)