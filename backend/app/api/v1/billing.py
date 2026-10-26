"""A business's own subscription and invoices (owners and admins)."""
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.config import settings
from app.core.deps import CurrentUser, DBSession, require_capability
from app.core.permissions import Capability
from app.modules.billing import service
from app.modules.billing.pdf import render_invoice_pdf
from app.schemas.billing import AccountStateOut, BillingOut, InvoiceOut, PayToOut, SubscriptionOut

router = APIRouter(
    prefix="/billing", tags=["billing"],
    dependencies=[Depends(require_capability(Capability.VIEW_BILLING))],
)


def _split(value: str) -> list[str]:
    return [p.strip() for p in (value or "").replace("\n", "|").split("|") if p.strip()]


def pay_to() -> PayToOut:
    return PayToOut(
        name=settings.BILLING_SELLER_NAME, address=_split(settings.BILLING_SELLER_ADDRESS),
        email=settings.BILLING_SELLER_EMAIL or None, tax_id=settings.BILLING_SELLER_TAX_ID or None,
        bank_details=_split(settings.BILLING_BANK_DETAILS),
    )


@router.get("", response_model=BillingOut)
async def my_billing(db: DBSession, user: CurrentUser) -> BillingOut:
    await service.issue_due_invoices(db, tenant_id=user.tenant_id)  # in case the server was asleep on the date
    sub = await service.get_subscription(db, user.tenant_id)
    acct = await service.account_state(db, user.tenant_id)
    return BillingOut(
        subscription=SubscriptionOut.model_validate(sub) if sub else None,
        account=AccountStateOut(**acct, message=service.state_message(acct, admin=True)),
        active_branches=await service.active_branches(db, user.tenant_id),
        unbilled_setup_branches=await service.unbilled_setup_branches(db, user.tenant_id, sub),
        invoices=[InvoiceOut.model_validate(i) for i in await service.list_invoices(db, user.tenant_id)],
        pay_to=pay_to(),
    )


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf(invoice_id: uuid.UUID, db: DBSession, user: CurrentUser) -> Response:
    invoice = await service.get_invoice(db, invoice_id, user.tenant_id)
    return Response(
        content=render_invoice_pdf(invoice), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{invoice.number}.pdf"'},
    )