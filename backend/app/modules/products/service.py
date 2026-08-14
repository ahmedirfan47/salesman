import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate


async def list_products(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    active_only: bool = False,
) -> list[Product]:
    stmt = select(Product).where(Product.tenant_id == tenant_id)
    if active_only:
        stmt = stmt.where(Product.is_active.is_(True))
    stmt = stmt.order_by(Product.created_at.desc()).limit(limit).offset(offset)
    return list(await db.scalars(stmt))


async def get_product(db: AsyncSession, tenant_id: uuid.UUID, product_id: uuid.UUID) -> Product:
    product = await db.scalar(
        select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id)
    )
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


async def create_product(db: AsyncSession, tenant_id: uuid.UUID, data: ProductCreate) -> Product:
    exists = await db.scalar(
        select(Product).where(Product.tenant_id == tenant_id, Product.sku == data.sku)
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, f"SKU '{data.sku}' already exists")

    product = Product(tenant_id=tenant_id, **data.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


async def update_product(
    db: AsyncSession, tenant_id: uuid.UUID, product_id: uuid.UUID, data: ProductUpdate
) -> Product:
    product = await get_product(db, tenant_id, product_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(product, key, value)
    await db.commit()
    await db.refresh(product)
    return product


async def delete_product(db: AsyncSession, tenant_id: uuid.UUID, product_id: uuid.UUID) -> None:
    product = await get_product(db, tenant_id, product_id)
    await db.delete(product)
    await db.commit()