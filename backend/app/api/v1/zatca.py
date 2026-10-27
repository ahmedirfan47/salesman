"""ZATCA e-invoicing: connect branches, follow every e-invoice, fix and resend rejections."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response

from app.core.branches import BranchScope
from app.core.deps import CurrentUser, DBSession, require_capability
from app.core.permissions import Capability
from app.db.models.tenant import Tenant
from app.modules.accounts import service as accounts
from app.modules.zatca import service
from app.schemas.zatca import Counts, DocumentOut, OnboardIn, OverviewOut, UnitIn, UnitOut

router = APIRouter(
    prefix="/zatca", tags=["zatca"],
    dependencies=[Depends(require_capability(Capability.VIEW_ACCOUNTS))],
)
_manage = Depends(require_capability(Capability.MANAGE_ACCOUNTS))


def _unit(u) -> UnitOut:
    out = UnitOut.model_validate(u)
    out.has_compliance_certificate = bool(u.compliance_token)
    return out


def _document(doc, inv) -> DocumentOut:
    buyer = inv.buyer or {}
    return DocumentOut(
        id=doc.id, branch_id=doc.branch_id, invoice_id=inv.id, invoice_number=inv.number,
        customer_id=inv.customer_id, buyer_name=buyer.get("company") or buyer.get("name"),
        issue_date=inv.issue_date, currency=inv.currency, total=inv.total, flow=doc.flow, kind=doc.kind,
        status=doc.status, icv=doc.icv, document_uuid=doc.document_uuid, invoice_hash=doc.invoice_hash,
        zatca_status=doc.zatca_status, errors=doc.errors or [], warnings=doc.warnings or [],
        last_error=doc.last_error, attempts=doc.attempts, signed_at=doc.signed_at,
        submitted_at=doc.submitted_at, created_at=doc.created_at, has_cleared_xml=bool(doc.cleared_xml),
    )


@router.get("", response_model=OverviewOut)
async def overview(db: DBSession, user: CurrentUser, scope: BranchScope) -> OverviewOut:
    settings = await accounts.get_settings(db, user.tenant_id)
    tenant = await db.get(Tenant, user.tenant_id)
    units = [u for u in await service.list_units(db, user.tenant_id) if scope is None or u.branch_id == scope]
    out = OverviewOut(
        seller_problems=service.seller_problems(settings, tenant),
        units=[_unit(u) for u in units],
        counts=Counts(**await service.counts(db, user.tenant_id, scope)),
    )
    await db.commit()
    return out


# ---- connecting a branch ----
@router.post("/units", response_model=UnitOut, status_code=201, dependencies=[_manage])
async def prepare_unit(data: UnitIn, db: DBSession, user: CurrentUser) -> UnitOut:
    unit = await service.prepare_unit(
        db, user.tenant_id, branch_id=data.branch_id, environment=data.environment, location=data.location,
        industry=data.industry, invoice_types=data.invoice_types, common_name=data.common_name,
    )
    return _unit(unit)


@router.post("/units/{unit_id}/onboard", response_model=UnitOut, dependencies=[_manage])
async def onboard(unit_id: uuid.UUID, data: OnboardIn, db: DBSession, user: CurrentUser) -> UnitOut:
    return _unit(await service.onboard(db, user.tenant_id, unit_id, data.otp))


@router.post("/units/{unit_id}/disable", response_model=UnitOut, dependencies=[_manage])
async def disable(unit_id: uuid.UUID, db: DBSession, user: CurrentUser) -> UnitOut:
    return _unit(await service.disable_unit(db, user.tenant_id, unit_id))


@router.post("/units/{unit_id}/enable", response_model=UnitOut, dependencies=[_manage])
async def enable(unit_id: uuid.UUID, db: DBSession, user: CurrentUser) -> UnitOut:
    return _unit(await service.enable_unit(db, user.tenant_id, unit_id))


# ---- e-invoices ----
@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    db: DBSession, user: CurrentUser, scope: BranchScope,
    status: Literal["attention", "waiting", "done", "cleared", "reported", "rejected", "blocked", "queued",
                    "superseded"] | None = None,
    flow: Literal["standard", "simplified"] | None = None,
) -> list[DocumentOut]:
    rows = await service.list_documents(db, user.tenant_id, status_=status, flow=flow, scope=scope)
    return [_document(d, i) for d, i in rows]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope) -> DocumentOut:
    doc = await service.get_document(db, user.tenant_id, document_id, scope)
    inv = await accounts.get_invoice(db, user.tenant_id, doc.invoice_id)
    return _document(doc, inv)


@router.get("/documents/{document_id}/xml")
async def document_xml(document_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope) -> Response:
    """The legal XML: as cleared by ZATCA for standard invoices, as signed for simplified ones."""
    doc = await service.get_document(db, user.tenant_id, document_id, scope)
    inv = await accounts.get_invoice(db, user.tenant_id, doc.invoice_id)
    content = doc.cleared_xml or doc.xml
    if not content:
        raise HTTPException(404, "This e-invoice hasn't been signed")
    return Response(content=content.encode(), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{inv.number}.xml"'})


@router.post("/documents/{document_id}/send", response_model=DocumentOut, dependencies=[_manage])
async def send_again(document_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope) -> DocumentOut:
    doc = await service.send_again(db, user.tenant_id, document_id, scope)
    inv = await accounts.get_invoice(db, user.tenant_id, doc.invoice_id)
    return _document(doc, inv)


@router.post("/documents/{document_id}/resubmit", response_model=DocumentOut, dependencies=[_manage])
async def resubmit(document_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope) -> DocumentOut:
    doc = await service.resubmit(db, user.tenant_id, document_id, scope)
    inv = await accounts.get_invoice(db, user.tenant_id, doc.invoice_id)
    return _document(doc, inv)


@router.post("/invoices/{invoice_id}/stamp", response_model=DocumentOut, dependencies=[_manage])
async def stamp_invoice(invoice_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope) -> DocumentOut:
    doc = await service.stamp_now(db, user.tenant_id, invoice_id, scope)
    inv = await accounts.get_invoice(db, user.tenant_id, doc.invoice_id)
    return _document(doc, inv)