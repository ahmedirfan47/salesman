import hashlib
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select

from app.core.branches import BranchScope, in_scope, resolve_branch
from app.core.deps import CurrentUser, DBSession, require_role
from app.core.enums import UserRole
from app.db.models.price_list import PriceList
from app.modules.pricing import service
from app.modules.pricing.excel_parser import ExcelParseError, parse_price_sheet
from app.schemas.pricing import (
    CurrentPriceOut,
    PriceListCreate,
    PriceListOut,
    ProductPriceOut,
)

router = APIRouter(prefix="/pricing", tags=["pricing"])

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@router.get("/price-lists", response_model=list[PriceListOut])
async def list_price_lists(db: DBSession, user: CurrentUser, scope: BranchScope) -> list[PriceListOut]:
    return await service.list_price_lists(db, user.tenant_id, scope)


@router.post(
    "/price-lists",
    response_model=PriceListOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def create_price_list(
    data: PriceListCreate,
    db: DBSession,
    user: CurrentUser,
    scope: BranchScope,
    branch_id: uuid.UUID | None = Query(None, description="branch this list is for"),
) -> PriceListOut:
    """Create a DRAFT price list from JSON lines (manual entry)."""
    branch = await resolve_branch(db, user.tenant_id, scope, branch_id, required=True)
    return await service.create_price_list(db, user.tenant_id, data, branch_id=branch, uploaded_by=user.id)


@router.post(
    "/price-lists/upload",
    response_model=PriceListOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def upload_price_sheet(
    db: DBSession,
    user: CurrentUser,
    scope: BranchScope,
    file: UploadFile = File(...),
    branch_id: uuid.UUID | None = Query(None, description="branch this sheet is for"),
) -> PriceListOut:
    """Upload an .xlsx price sheet for one branch -> parsed into a DRAFT price list.

    Review the draft, then call /activate to make it that branch's live prices and stock.
    """
    branch = await resolve_branch(db, user.tenant_id, scope, branch_id, required=True)
    filename = file.filename or "upload.xlsx"
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only .xlsx files are supported."
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File exceeds the 10 MB limit."
        )

    file_hash = hashlib.sha256(content).hexdigest()

    try:
        lines = parse_price_sheet(content)
    except ExcelParseError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    data = PriceListCreate(source_filename=filename, lines=lines)
    return await service.create_price_list(
        db, user.tenant_id, data, branch_id=branch, uploaded_by=user.id, file_hash=file_hash
    )


@router.post(
    "/price-lists/{price_list_id}/activate",
    response_model=PriceListOut,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def activate_price_list(
    price_list_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope
) -> PriceListOut:
    branch_id = await db.scalar(
        select(PriceList.branch_id).where(PriceList.id == price_list_id, PriceList.tenant_id == user.tenant_id)
    )
    if branch_id is None or not in_scope(scope, branch_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price list not found")
    return await service.activate_price_list(db, user.tenant_id, price_list_id, actor_id=user.id)


@router.get("/current/{sku}", response_model=CurrentPriceOut)
async def get_current_price(sku: str, db: DBSession, user: CurrentUser, scope: BranchScope) -> CurrentPriceOut:
    branch = await resolve_branch(db, user.tenant_id, scope)
    result = await service.get_current_price(db, user.tenant_id, sku, branch)
    if not result:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No active price for SKU '{sku}'")
    return result


@router.get("/history/{product_id}", response_model=list[ProductPriceOut])
async def price_history(
    product_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope
) -> list[ProductPriceOut]:
    return await service.price_history(db, user.tenant_id, product_id, scope)