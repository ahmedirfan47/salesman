import uuid

from fastapi import APIRouter, Depends, Query, status

from app.core.branches import BranchScope
from app.core.deps import CurrentUser, DBSession, require_role
from app.core.enums import UserRole
from app.modules.products import service
from app.schemas.product import ProductCatalogRow, ProductCreate, ProductOut, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductOut])
async def list_products(
    db: DBSession,
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    active_only: bool = False,
) -> list[ProductOut]:
    return await service.list_products(
        db, user.tenant_id, limit=limit, offset=offset, active_only=active_only
    )


@router.get("/catalog", response_model=list[ProductCatalogRow])
async def product_catalog(db: DBSession, user: CurrentUser, scope: BranchScope) -> list[ProductCatalogRow]:
    """Products with current price + stock, for the dashboard products table."""
    return await service.list_catalog(db, user.tenant_id, scope)


@router.post(
    "",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def create_product(data: ProductCreate, db: DBSession, user: CurrentUser) -> ProductOut:
    return await service.create_product(db, user.tenant_id, data)


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(product_id: uuid.UUID, db: DBSession, user: CurrentUser) -> ProductOut:
    return await service.get_product(db, user.tenant_id, product_id)


@router.patch(
    "/{product_id}",
    response_model=ProductOut,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def update_product(
    product_id: uuid.UUID, data: ProductUpdate, db: DBSession, user: CurrentUser
) -> ProductOut:
    return await service.update_product(db, user.tenant_id, product_id, data)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def delete_product(product_id: uuid.UUID, db: DBSession, user: CurrentUser) -> None:
    await service.delete_product(db, user.tenant_id, product_id)