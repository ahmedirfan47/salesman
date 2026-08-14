import hashlib
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core.deps import CurrentUser, DBSession, require_role
from app.core.enums import UserRole
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
async def list_price_lists(db: DBSession, user: CurrentUser) -> list[PriceListOut]:
    return await service.list_price_lists(db, user.tenant_id)


@router.post(
    "/price-lists",
    response_model=PriceListOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def create_price_list(
    data: PriceListCreate, db: DBSession, user: CurrentUser
) -> PriceListOut:
    """Create a DRAFT price list from JSON lines (manual entry)."""
    return await service.create_price_list(db, user.tenant_id, data, uploaded_by=user.id)


@router.post(
    "/price-lists/upload",
    response_model=PriceListOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def upload_price_sheet(
    db: DBSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> PriceListOut:
    """Upload an .xlsx price sheet -> parsed into a DRAFT price list (not yet live).

    Review the draft, then call /activate to make it the active price/stock.
    """
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
        db, user.tenant_id, data, uploaded_by=user.id, file_hash=file_hash
    )


@router.post(
    "/price-lists/{price_list_id}/activate",
    response_model=PriceListOut,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def activate_price_list(
    price_list_id: uuid.UUID, db: DBSession, user: CurrentUser
) -> PriceListOut:
    return await service.activate_price_list(db, user.tenant_id, price_list_id, actor_id=user.id)


@router.get("/current/{sku}", response_model=CurrentPriceOut)
async def get_current_price(sku: str, db: DBSession, user: CurrentUser) -> CurrentPriceOut:
    result = await service.get_current_price(db, user.tenant_id, sku)
    if not result:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No active price for SKU '{sku}'")
    return result


@router.get("/history/{product_id}", response_model=list[ProductPriceOut])
async def price_history(
    product_id: uuid.UUID, db: DBSession, user: CurrentUser
) -> list[ProductPriceOut]:
    return await service.price_history(db, user.tenant_id, product_id)