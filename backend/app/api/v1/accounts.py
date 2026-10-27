"""Customer accounts: receivables, invoices, payments, credit notes, credit terms and statements."""
import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response

from app.core.branches import BranchScope
from app.core.deps import CurrentUser, DBSession, require_capability
from app.core.permissions import Capability
from app.db.models.order import Order
from app.modules.accounts import pdf as account_pdf
from app.modules.accounts import service
from app.modules.zatca import service as zatca
from app.schemas.accounts import (
    AccountRow, AccountSettingsIn, AccountSettingsOut, AccountsOut, AllocationOut, CreditNoteIn, CreditTermsIn,
    CustomerAccountOut, EInvoiceSummary, OpeningBalanceIn, PaymentIn, PaymentOut, SalesInvoiceDetailOut,
    SalesInvoiceOut, StatementOut, TaxDetailsIn, TaxDetailsOut, VoidPaymentIn,
)

router = APIRouter(
    prefix="/accounts", tags=["accounts"],
    dependencies=[Depends(require_capability(Capability.VIEW_ACCOUNTS))],
)
_manage = Depends(require_capability(Capability.MANAGE_ACCOUNTS))


def _pdf(content: bytes, filename: str) -> Response:
    return Response(
        content=content, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _summary(doc) -> EInvoiceSummary | None:
    return EInvoiceSummary(document_id=doc.id, flow=doc.flow, status=doc.status) if doc is not None else None


async def _invoices_out(db, rows) -> list[SalesInvoiceOut]:
    docs = await zatca.documents_for(db, [r.id for r in rows])
    out = []
    for r in rows:
        item = SalesInvoiceOut.model_validate(r)
        item.einvoice = _summary(docs.get(r.id))
        out.append(item)
    return out


async def _invoice_detail(db, inv) -> SalesInvoiceDetailOut:
    out = SalesInvoiceDetailOut.model_validate(inv)
    out.einvoice = _summary(await zatca.latest_document(db, inv.id))
    out.payments = [
        AllocationOut(payment_id=p.id, payment_number=p.number, paid_on=p.paid_on, method=p.method, amount=a.amount)
        for a, p in await service.allocations_for_invoice(db, inv.id)
    ]
    if inv.kind != "credit_note":
        notes = await service.list_invoices(db, inv.tenant_id, kind="credit_note", customer_id=inv.customer_id)
        out.credit_notes = await _invoices_out(db, [n for n in notes if n.original_invoice_id == inv.id])
    return out


# ---- settings ----
@router.get("/settings", response_model=AccountSettingsOut)
async def get_settings(db: DBSession, user: CurrentUser) -> AccountSettingsOut:
    row = await service.get_settings(db, user.tenant_id)
    await db.commit()
    return AccountSettingsOut.model_validate(row)


@router.put("/settings", response_model=AccountSettingsOut, dependencies=[_manage])
async def update_settings(data: AccountSettingsIn, db: DBSession, user: CurrentUser) -> AccountSettingsOut:
    row = await service.update_settings(db, user.tenant_id, data.model_dump(exclude_unset=True))
    return AccountSettingsOut.model_validate(row)


# ---- receivables overview ----
@router.get("", response_model=AccountsOut)
async def list_accounts(db: DBSession, user: CurrentUser, scope: BranchScope) -> AccountsOut:
    rows, totals = await service.list_accounts(db, user.tenant_id, scope)
    return AccountsOut(totals=totals, customers=rows)


@router.get("/customers/{customer_id}", response_model=CustomerAccountOut)
async def customer_account(customer_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope) -> CustomerAccountOut:
    customer = await service.get_customer(db, user.tenant_id, customer_id, scope)
    summary = await service.account_summary(db, user.tenant_id, customer)
    invoices = await service.list_invoices(db, user.tenant_id, customer_id=customer.id, limit=100)
    payments = await service.list_payments(db, user.tenant_id, customer_id=customer.id, limit=100)
    await db.commit()
    return CustomerAccountOut(
        account=AccountRow(**summary), vat_number=customer.vat_number, tax=TaxDetailsOut.model_validate(customer),
        own_credit_limit=customer.credit_limit, own_payment_terms_days=customer.payment_terms_days,
        invoices=await _invoices_out(db, invoices),
        payments=[PaymentOut.model_validate(p) for p in payments],
    )


@router.patch("/customers/{customer_id}/credit", response_model=AccountRow, dependencies=[_manage])
async def update_credit(
    customer_id: uuid.UUID, data: CreditTermsIn, db: DBSession, user: CurrentUser, scope: BranchScope,
) -> AccountRow:
    customer = await service.get_customer(db, user.tenant_id, customer_id, scope)
    for key, value in data.model_dump(exclude_unset=True).items():
        if key == "on_hold":
            if value is not None:
                customer.on_hold = value
        elif key == "vat_number":
            customer.vat_number = (value or "").strip() or None
        else:
            setattr(customer, key, value)
    await db.commit()
    await db.refresh(customer)
    summary = await service.account_summary(db, user.tenant_id, customer)
    await db.commit()
    return AccountRow(**summary)


@router.patch("/customers/{customer_id}/tax-details", response_model=TaxDetailsOut, dependencies=[_manage])
async def update_tax_details(
    customer_id: uuid.UUID, data: TaxDetailsIn, db: DBSession, user: CurrentUser, scope: BranchScope,
) -> TaxDetailsOut:
    """VAT and CR numbers and the national address. With a VAT or CR number, invoices are standard (B2B)."""
    customer = await service.get_customer(db, user.tenant_id, customer_id, scope)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(customer, key, (value or "").strip() or None)
    await db.commit()
    await db.refresh(customer)
    return TaxDetailsOut.model_validate(customer)


@router.get("/customers/{customer_id}/statement", response_model=StatementOut)
async def statement(
    customer_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope,
    start: date | None = None, end: date | None = None,
) -> StatementOut:
    customer = await service.get_customer(db, user.tenant_id, customer_id, scope)
    data = await service.statement(db, user.tenant_id, customer, start=start, end=end)
    return StatementOut(**{**data, "summary": AccountRow(**data["summary"])})


@router.get("/customers/{customer_id}/statement/pdf")
async def statement_pdf(
    customer_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope,
    start: date | None = None, end: date | None = None,
) -> Response:
    customer = await service.get_customer(db, user.tenant_id, customer_id, scope)
    data = await service.statement(db, user.tenant_id, customer, start=start, end=end)
    return _pdf(account_pdf.render_statement_pdf(data), account_pdf.statement_filename(data))


@router.post("/customers/{customer_id}/opening-balance", response_model=SalesInvoiceOut, status_code=201,
             dependencies=[_manage])
async def opening_balance(
    customer_id: uuid.UUID, data: OpeningBalanceIn, db: DBSession, user: CurrentUser, scope: BranchScope,
) -> SalesInvoiceOut:
    inv = await service.add_opening_balance(
        db, user.tenant_id, customer_id, amount=data.amount, as_of=data.as_of, due_date=data.due_date,
        note=data.note, actor_id=user.id, scope=scope,
    )
    return SalesInvoiceOut.model_validate(inv)


# ---- invoices and credit notes ----
@router.get("/invoices", response_model=list[SalesInvoiceOut])
async def list_invoices(
    db: DBSession, user: CurrentUser, scope: BranchScope,
    customer_id: uuid.UUID | None = None,
    status: Literal["open", "partially_paid", "paid", "issued", "unpaid", "overdue"] | None = None,
    kind: Literal["invoice", "credit_note", "opening_balance"] | None = None,
) -> list[SalesInvoiceOut]:
    rows = await service.list_invoices(db, user.tenant_id, scope=scope, customer_id=customer_id, status_=status, kind=kind)
    return await _invoices_out(db, rows)


@router.get("/invoices/{invoice_id}", response_model=SalesInvoiceDetailOut)
async def get_invoice(invoice_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope) -> SalesInvoiceDetailOut:
    inv = await service.get_invoice(db, user.tenant_id, invoice_id, scope)
    return await _invoice_detail(db, inv)


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf(invoice_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope) -> Response:
    inv = await service.get_invoice(db, user.tenant_id, invoice_id, scope)
    return _pdf(account_pdf.render_invoice_pdf(inv, await zatca.einvoice_for_pdf(db, inv)), f"{inv.number}.pdf")


@router.post("/invoices/{invoice_id}/credit-note", response_model=SalesInvoiceOut, status_code=201, dependencies=[_manage])
async def credit_note(
    invoice_id: uuid.UUID, data: CreditNoteIn, db: DBSession, user: CurrentUser, scope: BranchScope,
) -> SalesInvoiceOut:
    note = await service.issue_credit_note(
        db, user.tenant_id, invoice_id, amount=data.amount, reason=data.reason, actor_id=user.id, scope=scope,
    )
    return (await _invoices_out(db, [note]))[0]


@router.get("/orders/{order_id}/invoice", response_model=SalesInvoiceDetailOut | None)
async def order_invoice(order_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope) -> SalesInvoiceDetailOut | None:
    inv = await service.invoice_for_order(db, order_id)
    if inv is None or inv.tenant_id != user.tenant_id or (scope is not None and inv.branch_id != scope):
        return None
    return await _invoice_detail(db, inv)


@router.post("/orders/{order_id}/invoice", response_model=SalesInvoiceDetailOut, status_code=201, dependencies=[_manage])
async def issue_order_invoice(order_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope) -> SalesInvoiceDetailOut:
    """Issue an order's invoice now instead of waiting for delivery."""
    from app.modules.orders import service as orders_service

    order: Order = await orders_service.get_order(db, user.tenant_id, order_id, scope)
    inv = await service.issue_invoice_for_order(db, order, actor_id=user.id)
    return await _invoice_detail(db, inv)


# ---- payments ----
@router.get("/payments", response_model=list[PaymentOut])
async def list_payments(
    db: DBSession, user: CurrentUser, scope: BranchScope, customer_id: uuid.UUID | None = None,
) -> list[PaymentOut]:
    rows = await service.list_payments(db, user.tenant_id, scope=scope, customer_id=customer_id)
    return [PaymentOut.model_validate(r) for r in rows]


@router.post("/payments", response_model=PaymentOut, status_code=201, dependencies=[_manage])
async def record_payment(data: PaymentIn, db: DBSession, user: CurrentUser, scope: BranchScope) -> PaymentOut:
    payment = await service.record_payment(
        db, user.tenant_id, customer_id=data.customer_id, invoice_id=data.invoice_id, amount=data.amount,
        method=data.method, reference=data.reference, paid_on=data.paid_on, notes=data.notes,
        actor_id=user.id, scope=scope,
    )
    return PaymentOut.model_validate(payment)


@router.post("/payments/{payment_id}/void", response_model=PaymentOut, dependencies=[_manage])
async def void_payment(
    payment_id: uuid.UUID, data: VoidPaymentIn, db: DBSession, user: CurrentUser, scope: BranchScope,
) -> PaymentOut:
    payment = await service.void_payment(db, user.tenant_id, payment_id, reason=data.reason, actor_id=user.id, scope=scope)
    return PaymentOut.model_validate(payment)