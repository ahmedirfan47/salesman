import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PaymentMethod = Literal["cash", "bank_transfer", "cheque", "card", "other"]


# ---- settings ----
class AccountSettingsIn(BaseModel):
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    vat_rate: Decimal | None = Field(default=None, ge=0, le=100)
    prices_include_vat: bool | None = None
    invoice_on: Literal["confirmed", "delivered"] | None = None
    default_payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    default_credit_limit: Decimal | None = Field(default=None, ge=0)
    hold_over_limit: bool | None = None
    hold_when_overdue: bool | None = None
    overdue_grace_days: int | None = Field(default=None, ge=0, le=365)
    seller_name: str | None = Field(default=None, max_length=255)
    seller_name_ar: str | None = Field(default=None, max_length=255)
    seller_vat_number: str | None = Field(default=None, max_length=20)
    seller_cr_number: str | None = Field(default=None, max_length=20)
    seller_address: str | None = Field(default=None, max_length=500)
    seller_street: str | None = Field(default=None, max_length=255)
    seller_building_number: str | None = Field(default=None, max_length=8)
    seller_district: str | None = Field(default=None, max_length=127)
    seller_city: str | None = Field(default=None, max_length=127)
    seller_postal_code: str | None = Field(default=None, max_length=10)
    invoice_footer: str | None = Field(default=None, max_length=2000)


class AccountSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    currency: str
    vat_rate: Decimal
    prices_include_vat: bool
    invoice_on: str
    default_payment_terms_days: int
    default_credit_limit: Decimal | None
    hold_over_limit: bool
    hold_when_overdue: bool
    overdue_grace_days: int
    seller_name: str | None
    seller_name_ar: str | None
    seller_vat_number: str | None
    seller_cr_number: str | None
    seller_address: str | None
    seller_street: str | None
    seller_building_number: str | None
    seller_district: str | None
    seller_city: str | None
    seller_postal_code: str | None
    invoice_footer: str | None


# ---- customer credit ----
class CreditTermsIn(BaseModel):
    """Send a field as null to fall back to the business default (limit/terms) or clear it (VAT no.)."""
    credit_limit: Decimal | None = Field(default=None, ge=0)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    on_hold: bool | None = None
    vat_number: str | None = Field(default=None, max_length=20)


class TaxDetailsIn(BaseModel):
    """The customer's tax registration and national address (B2B e-invoices need them)."""
    vat_number: str | None = Field(default=None, max_length=20)
    cr_number: str | None = Field(default=None, max_length=20)
    street: str | None = Field(default=None, max_length=255)
    building_number: str | None = Field(default=None, max_length=8)
    district: str | None = Field(default=None, max_length=127)
    city: str | None = Field(default=None, max_length=127)
    postal_code: str | None = Field(default=None, max_length=10)


class TaxDetailsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vat_number: str | None
    cr_number: str | None
    street: str | None
    building_number: str | None
    district: str | None
    city: str | None
    postal_code: str | None


class Aging(BaseModel):
    current: Decimal
    days_1_30: Decimal
    days_31_60: Decimal
    days_61_90: Decimal
    days_90_plus: Decimal


class AccountRow(BaseModel):
    customer_id: uuid.UUID
    name: str
    company: str | None
    branch_id: uuid.UUID
    whatsapp_number: str | None
    currency: str
    balance: Decimal
    uninvoiced: Decimal
    exposure: Decimal
    credit_limit: Decimal | None
    available_credit: Decimal | None
    over_limit: bool
    payment_terms_days: int
    on_hold: bool
    overdue: Decimal
    oldest_overdue_days: int
    blocking_overdue: Decimal
    unapplied: Decimal
    open_invoices: int
    aging: Aging


class AccountTotals(BaseModel):
    currency: str
    receivable: Decimal
    overdue: Decimal
    customers_overdue: int
    customers_over_limit: int
    customers_on_hold: int
    unapplied: Decimal
    aging: Aging


class AccountsOut(BaseModel):
    totals: AccountTotals
    customers: list[AccountRow]


# ---- invoices ----
class InvoiceLineOut(BaseModel):
    sku: str | None = None
    name: str
    quantity: str
    unit_price: str
    net: str
    vat_rate: str
    vat: str
    total: str


class EInvoiceSummary(BaseModel):
    """The invoice's ZATCA e-invoice, if its branch is connected."""
    document_id: uuid.UUID
    flow: str
    status: str


class SalesInvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    branch_id: uuid.UUID
    customer_id: uuid.UUID | None
    order_id: uuid.UUID | None
    original_invoice_id: uuid.UUID | None
    kind: str
    number: str
    issue_date: date
    due_date: date
    currency: str
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
    amount_paid: Decimal
    amount_credited: Decimal
    balance_due: Decimal
    status: str
    buyer: dict
    reason: str | None
    created_at: datetime
    einvoice: EInvoiceSummary | None = None


class AllocationOut(BaseModel):
    payment_id: uuid.UUID
    payment_number: str
    paid_on: date
    method: str
    amount: Decimal


class SalesInvoiceDetailOut(SalesInvoiceOut):
    lines: list[InvoiceLineOut]
    seller: dict
    notes: str | None
    payments: list[AllocationOut] = []
    credit_notes: list[SalesInvoiceOut] = []


class CreditNoteIn(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, description="incl. VAT; leave empty to credit the whole invoice")
    reason: str = Field(min_length=1, max_length=255)


class OpeningBalanceIn(BaseModel):
    amount: Decimal = Field(gt=0)
    as_of: date | None = None
    due_date: date | None = None
    note: str | None = Field(default=None, max_length=255)


# ---- payments ----
class PaymentIn(BaseModel):
    customer_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=0)
    method: PaymentMethod
    reference: str | None = Field(default=None, max_length=120)
    paid_on: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    branch_id: uuid.UUID
    customer_id: uuid.UUID | None
    number: str
    amount: Decimal
    currency: str
    method: str
    reference: str | None
    paid_on: date
    notes: str | None
    unallocated: Decimal
    voided_at: datetime | None
    void_reason: str | None
    created_at: datetime


class VoidPaymentIn(BaseModel):
    reason: str = Field(min_length=1, max_length=255)


# ---- account detail and statements ----
class StatementLine(BaseModel):
    date: date
    kind: str
    document_number: str
    description: str
    debit: Decimal
    credit: Decimal
    balance: Decimal
    invoice_id: uuid.UUID | None
    payment_id: uuid.UUID | None


class StatementOut(BaseModel):
    customer: dict
    currency: str
    start: date
    end: date
    generated_on: date
    opening_balance: Decimal
    total_debits: Decimal
    total_credits: Decimal
    closing_balance: Decimal
    lines: list[StatementLine]
    summary: AccountRow


class CustomerAccountOut(BaseModel):
    account: AccountRow
    vat_number: str | None
    tax: TaxDetailsOut
    own_credit_limit: Decimal | None
    own_payment_terms_days: int | None
    invoices: list[SalesInvoiceOut]
    payments: list[PaymentOut]