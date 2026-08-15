import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.inventory import Inventory
from app.db.models.product import Product
from app.db.models.product_price import ProductPrice
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


async def list_catalog(db: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
    """Products enriched with current price + stock (for the dashboard table)."""
    rows = await db.execute(
        select(
            Product.id,
            Product.sku,
            Product.name_en,
            Product.name_ar,
            Product.category,
            Product.is_active,
            ProductPrice.unit_price,
            ProductPrice.currency,
            Inventory.quantity_on_hand,
        )
        .outerjoin(
            ProductPrice,
            (ProductPrice.product_id == Product.id) & (ProductPrice.effective_to.is_(None)),
        )
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .where(Product.tenant_id == tenant_id)
        .order_by(Product.sku)
    )
    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "sku": r.sku,
            "name_en": r.name_en,
            "name_ar": r.name_ar,
            "category": r.category,
            "is_active": r.is_active,
            "unit_price": float(r.unit_price) if r.unit_price is not None else None,
            "currency": r.currency,
            "stock": r.quantity_on_hand if r.quantity_on_hand is not None else 0,
        })
    return out