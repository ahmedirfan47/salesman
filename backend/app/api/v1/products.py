import uuid

from fastapi import APIRouter, Depends, Query, status

from app.core.branches import BranchScope
from app.core.deps import CurrentUser, DBSession, require_capability, require_role
from app.core.enums import UserRole
from app.core.permissions import Capability
from app.modules.products import matching, service
from app.schemas.product import (
    ProductAliasIn, ProductAliasOut, ProductCatalogRow, ProductCreate, ProductMatchOut, ProductOut, ProductUpdate,
)

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


# --- aliases: what customers call each product ---------------------------------------
_manage_products = Depends(require_capability(Capability.MANAGE_PRODUCTS))


@router.get("/aliases", response_model=list[ProductAliasOut])
async def list_aliases(
    db: DBSession, user: CurrentUser, product_id: uuid.UUID | None = Query(default=None),
) -> list[ProductAliasOut]:
    """Every alias the AI knows, most used first (or one product's)."""
    return [ProductAliasOut(**a) for a in await matching.list_aliases(db, user.tenant_id, product_id=product_id)]


@router.get("/match", response_model=list[ProductMatchOut])
async def match_products(
    db: DBSession, user: CurrentUser, q: str = Query(min_length=1, max_length=200),
    customer_id: uuid.UUID | None = Query(default=None),
) -> list[ProductMatchOut]:
    """Try the matcher: which products would the AI pick for these words?"""
    found = await matching.find_matches(db, user.tenant_id, q, customer_id=customer_id, limit=8)
    await db.commit()
    return [
        ProductMatchOut(product_id=m["product"].id, sku=m["product"].sku, name_en=m["product"].name_en,
                        name_ar=m["product"].name_ar, score=m["score"], matched_by=m["via"])
        for m in found
    ]


@router.post("/{product_id}/aliases", response_model=ProductAliasOut, status_code=status.HTTP_201_CREATED,
             dependencies=[_manage_products])
async def add_alias(product_id: uuid.UUID, data: ProductAliasIn, db: DBSession, user: CurrentUser) -> ProductAliasOut:
    row = await matching.add_alias(db, user.tenant_id, product_id, data.alias, customer_id=data.customer_id,
                                   actor_id=user.id)
    listed = await matching.list_aliases(db, user.tenant_id, product_id=product_id)
    return ProductAliasOut(**next(a for a in listed if a["id"] == row.id))


@router.delete("/aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_manage_products])
async def delete_alias(alias_id: uuid.UUID, db: DBSession, user: CurrentUser) -> None:
    await matching.delete_alias(db, user.tenant_id, alias_id)


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