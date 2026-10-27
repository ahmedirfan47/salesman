"""Customer accounts: what each customer owes the business, and why.

- AccountSettings: one row per business -- VAT, when invoices are issued,
  default payment terms and the credit rules applied to new orders.
- SalesInvoice: a tax invoice for an order, a credit note against an
  invoice, or a customer's opening balance carried over from an old system.
  Invoices are never deleted or voided; mistakes are corrected with a credit
  note (the same rule ZATCA applies).
- CustomerPayment + PaymentAllocation: money received, and which invoices it
  paid. Money not yet matched to an invoice stays on account and is applied
  automatically to the next invoice.
- AccountEntry: the customer ledger. One immutable row per invoice, credit
  note, payment or reversal. A customer's balance is the sum of its rows, and
  statements are read straight from it.
- DocumentCounter: gap-free numbering per business and document type.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class AccountSettings(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "account_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), default="SAR", nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("15.00"), nullable=False)
    # True when the price list already includes VAT
    prices_include_vat: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # "delivered" (default) or "confirmed": when an order's invoice is issued
    invoice_on: Mapped[str] = mapped_column(String(16), default="delivered", nullable=False)
    # days a customer has to pay; 0 = due on the invoice date
    default_payment_terms_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    # applied to customers without their own limit; NULL = no limit
    default_credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    # hold new orders for approval when they would take a customer over their limit
    hold_over_limit: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # hold new orders while a customer has invoices overdue by more than overdue_grace_days
    hold_when_overdue: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    overdue_grace_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # the seller as printed on invoices and statements (and sent to ZATCA later)
    seller_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seller_name_ar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seller_vat_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    seller_cr_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    seller_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # the national address, as ZATCA e-invoices need it
    seller_street: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seller_building_number: Mapped[str | None] = mapped_column(String(8), nullable=True)
    seller_district: Mapped[str | None] = mapped_column(String(127), nullable=True)
    seller_city: Mapped[str | None] = mapped_column(String(127), nullable=True)
    seller_postal_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    invoice_footer: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentCounter(Base):
    """Last number used per business and document type (row-locked when incremented)."""

    __tablename__ = "document_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class SalesInvoice(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "sales_invoices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="uq_sales_invoice_number"),
        Index("ix_sales_invoices_open", "tenant_id", "customer_id", "status"),
        # one invoice per order (credit notes reference the order too, so kind is part of it)
        Index("uq_sales_invoice_order", "order_id", unique=True,
              postgresql_where="kind = 'invoice' AND order_id IS NOT NULL"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), index=True, nullable=False
    )
    # NULL for walk-in customers: the invoice exists but isn't on any account
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), index=True, nullable=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), index=True, nullable=True
    )
    # invoice | credit_note | opening_balance
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    # for a credit note: the invoice it corrects
    original_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_invoices.id"), nullable=True
    )
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # [{sku, name, quantity, unit_price, net, vat_rate, vat, total}] -- amounts as strings
    lines: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    # invoices only: what has been paid and credited against it
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    amount_credited: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    # invoices: open | partially_paid | paid ; credit notes: issued
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    seller: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    buyer: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    @property
    def balance_due(self) -> Decimal:
        if self.kind == "credit_note":
            return Decimal("0")
        return max(Decimal(self.total) - Decimal(self.amount_paid) - Decimal(self.amount_credited), Decimal("0"))


class CustomerPayment(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "customer_payments"
    __table_args__ = (UniqueConstraint("tenant_id", "number", name="uq_customer_payment_number"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), index=True, nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), index=True, nullable=True
    )
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # cash | bank_transfer | cheque | card | other
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # part of the payment not yet matched to an invoice
    unallocated: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class PaymentAllocation(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "payment_allocations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_payments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_invoices.id"), index=True, nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)


class AccountEntry(UUIDPKMixin, TimestampMixin, Base):
    """One line of a customer's ledger. Never updated or deleted."""

    __tablename__ = "account_entries"
    __table_args__ = (Index("ix_account_entries_customer_date", "tenant_id", "customer_id", "entry_date"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    # invoice | credit_note | opening_balance | payment | payment_void
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    document_number: Mapped[str] = mapped_column(String(32), nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sales_invoices.id"), nullable=True
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer_payments.id"), nullable=True
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    # debit raises what the customer owes; credit lowers it
    debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"), nullable=False)