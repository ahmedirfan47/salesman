import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---- input (Stonic admin console) ----
class SubscriptionIn(BaseModel):
    status: Literal["active", "paused", "cancelled"] | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    setup_fee_per_branch: Decimal | None = Field(default=None, ge=0)
    monthly_fee_per_branch: Decimal | None = Field(default=None, ge=0)
    tax_percent: Decimal | None = Field(default=None, ge=0, le=100)
    payment_terms_days: int | None = Field(default=None, ge=0, le=120)
    grace_days: int | None = Field(default=None, ge=0, le=120)
    next_invoice_on: date | None = None
    billing_name: str | None = Field(default=None, max_length=255)
    billing_address: str | None = Field(default=None, max_length=500)
    billing_tax_id: str | None = Field(default=None, max_length=64)
    billing_email: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)


class SetupInvoiceIn(BaseModel):
    branches: int | None = Field(default=None, ge=1, le=500)  # default: every branch not yet invoiced


class InvoiceLineIn(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    quantity: Decimal = Field(gt=0, le=100000)
    unit_amount: Decimal = Field(ge=0)


class CustomInvoiceIn(BaseModel):
    lines: list[InvoiceLineIn] = Field(min_length=1, max_length=50)
    due_on: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class MarkPaidIn(BaseModel):
    paid_on: date | None = None
    reference: str | None = Field(default=None, max_length=120)


class VoidIn(BaseModel):
    reason: str = Field(min_length=1, max_length=255)


# ---- output ----
class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    currency: str
    setup_fee_per_branch: Decimal
    monthly_fee_per_branch: Decimal
    tax_percent: Decimal
    payment_terms_days: int
    grace_days: int
    next_invoice_on: date
    setup_billed_branches: int
    billing_name: str | None
    billing_address: str | None
    billing_tax_id: str | None
    billing_email: str | None
    notes: str | None
    cancelled_on: date | None


class InvoiceLineOut(BaseModel):
    description: str
    quantity: Decimal
    unit_amount: Decimal
    amount: Decimal


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    kind: str
    status: str
    currency: str
    lines: list[InvoiceLineOut]
    subtotal: Decimal
    tax_percent: Decimal
    tax_amount: Decimal
    total: Decimal
    bill_to: dict
    issued_on: date
    due_on: date
    period_start: date | None
    period_end: date | None
    paid_on: date | None
    payment_reference: str | None
    voided_on: date | None
    void_reason: str | None
    notes: str | None


class AccountStateOut(BaseModel):
    state: Literal["ok", "open", "overdue", "read_only"]
    read_only: bool
    open_invoices: int
    outstanding: Decimal
    overdue: Decimal
    currency: str
    oldest_invoice: str | None
    oldest_due_on: date | None
    read_only_from: date | None
    message: str | None = None


class PayToOut(BaseModel):
    name: str
    address: list[str]
    email: str | None
    tax_id: str | None
    bank_details: list[str]


class BillingOut(BaseModel):
    """What a business sees on its Billing & Plan page."""
    subscription: SubscriptionOut | None
    account: AccountStateOut
    active_branches: int
    unbilled_setup_branches: int
    invoices: list[InvoiceOut]
    pay_to: PayToOut


class TenantBillingOut(BaseModel):
    """One business, as listed in the Stonic admin console."""
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    active_branches: int
    users: int
    subscription: SubscriptionOut | None
    unbilled_setup_branches: int
    account: AccountStateOut


class TenantBillingDetailOut(TenantBillingOut):
    invoices: list[InvoiceOut]


class BillingRunOut(BaseModel):
    issued: int