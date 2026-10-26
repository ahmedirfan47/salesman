"""Stonic's admin console: subscriptions and invoices for every business.

Only users whose email is listed in PLATFORM_ADMIN_EMAILS can use these
routes; everyone else gets 404, so the console isn't advertised.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from app.core.deps import CurrentUser, DBSession
from app.modules.billing import service
from app.modules.billing.pdf import render_invoice_pdf
from app.schemas.billing import (
    AccountStateOut,
    BillingRunOut,
    CustomInvoiceIn,
    InvoiceOut,
    MarkPaidIn,
    SetupInvoiceIn,
    SubscriptionIn,
    SubscriptionOut,
    TenantBillingDetailOut,
    TenantBillingOut,
    VoidIn,
)


async def require_platform_admin(user: CurrentUser):
    if not service.is_platform_admin(user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return user


router = APIRouter(prefix="/platform", tags=["platform"], dependencies=[Depends(require_platform_admin)])


def _tenant_out(row: dict, cls=TenantBillingOut, **extra):
    acct = row["account"]
    return cls(
        **{k: v for k, v in row.items() if k not in ("subscription", "account")},
        subscription=SubscriptionOut.model_validate(row["subscription"]) if row["subscription"] else None,
        account=AccountStateOut(**acct, message=service.state_message(acct, admin=True)),
        **extra,
    )


async def _detail(db, tenant_id: uuid.UUID) -> TenantBillingDetailOut:
    tenant = await service.get_tenant(db, tenant_id)
    row = await service.tenant_overview(db, tenant)
    invoices = [InvoiceOut.model_validate(i) for i in await service.list_invoices(db, tenant_id)]
    return _tenant_out(row, TenantBillingDetailOut, invoices=invoices)


@router.get("/tenants", response_model=list[TenantBillingOut])
async def tenants(db: DBSession) -> list[TenantBillingOut]:
    return [_tenant_out(r) for r in await service.list_tenants(db)]


@router.get("/tenants/{tenant_id}", response_model=TenantBillingDetailOut)
async def tenant(tenant_id: uuid.UUID, db: DBSession) -> TenantBillingDetailOut:
    await service.issue_due_invoices(db, tenant_id=tenant_id)
    return await _detail(db, tenant_id)


@router.put("/tenants/{tenant_id}/subscription", response_model=TenantBillingDetailOut)
async def save_subscription(tenant_id: uuid.UUID, data: SubscriptionIn, db: DBSession) -> TenantBillingDetailOut:
    await service.upsert_subscription(db, tenant_id, data.model_dump(exclude_unset=True))
    return await _detail(db, tenant_id)


@router.post("/tenants/{tenant_id}/invoices/setup", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
async def setup_invoice(tenant_id: uuid.UUID, data: SetupInvoiceIn, db: DBSession) -> InvoiceOut:
    return InvoiceOut.model_validate(await service.issue_setup_invoice(db, tenant_id, branches=data.branches))


@router.post("/tenants/{tenant_id}/invoices/next", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
async def next_invoice(tenant_id: uuid.UUID, db: DBSession) -> InvoiceOut:
    """Issue the next monthly invoice now, ahead of its date."""
    return InvoiceOut.model_validate(await service.issue_next_monthly(db, tenant_id))


@router.post("/tenants/{tenant_id}/invoices", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
async def custom_invoice(tenant_id: uuid.UUID, data: CustomInvoiceIn, db: DBSession) -> InvoiceOut:
    invoice = await service.issue_custom_invoice(
        db, tenant_id, [line.model_dump() for line in data.lines], due_on=data.due_on, notes=data.notes,
    )
    return InvoiceOut.model_validate(invoice)


@router.post("/invoices/{invoice_id}/paid", response_model=InvoiceOut)
async def mark_paid(invoice_id: uuid.UUID, data: MarkPaidIn, db: DBSession) -> InvoiceOut:
    return InvoiceOut.model_validate(
        await service.mark_paid(db, invoice_id, paid_on=data.paid_on, reference=data.reference)
    )


@router.post("/invoices/{invoice_id}/reopen", response_model=InvoiceOut)
async def reopen(invoice_id: uuid.UUID, db: DBSession) -> InvoiceOut:
    return InvoiceOut.model_validate(await service.reopen(db, invoice_id))


@router.post("/invoices/{invoice_id}/void", response_model=InvoiceOut)
async def void(invoice_id: uuid.UUID, data: VoidIn, db: DBSession) -> InvoiceOut:
    return InvoiceOut.model_validate(await service.void(db, invoice_id, data.reason))


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf(invoice_id: uuid.UUID, db: DBSession) -> Response:
    invoice = await service.get_invoice(db, invoice_id)
    return Response(
        content=render_invoice_pdf(invoice), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{invoice.number}.pdf"'},
    )


@router.post("/billing/run", response_model=BillingRunOut)
async def run_billing(db: DBSession) -> BillingRunOut:
    """Issue every monthly invoice that is due (this also runs automatically every hour)."""
    return BillingRunOut(issued=await service.issue_due_invoices(db))