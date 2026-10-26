import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
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


async def list_catalog(db: AsyncSession, tenant_id: uuid.UUID, scope: uuid.UUID | None = None) -> list[dict]:
    """Products with current price + stock (for the dashboard table).

    For one branch: that branch's price and stock. For all branches: stock is
    the total across branches, and when branch prices differ the row carries
    the lowest and highest price instead of a single one.
    """
    products = list(await db.scalars(
        select(Product).where(Product.tenant_id == tenant_id).order_by(Product.sku)
    ))
    price_q = select(ProductPrice.product_id, ProductPrice.unit_price, ProductPrice.currency).where(
        ProductPrice.tenant_id == tenant_id, ProductPrice.effective_to.is_(None)
    )
    stock_q = select(Inventory.product_id, func.sum(Inventory.quantity_on_hand)).where(
        Inventory.tenant_id == tenant_id
    ).group_by(Inventory.product_id)
    if scope is not None:
        price_q = price_q.where(ProductPrice.branch_id == scope)
        stock_q = stock_q.where(Inventory.branch_id == scope)

    prices: dict = {}
    for pid, price, currency in await db.execute(price_q):
        prices.setdefault(pid, []).append((float(price), currency))
    stock = {pid: int(qty or 0) for pid, qty in await db.execute(stock_q)}

    out = []
    for p in products:
        rows = prices.get(p.id, [])
        values = [v for v, _ in rows]
        low, high = (min(values), max(values)) if values else (None, None)
        out.append({
            "id": p.id,
            "sku": p.sku,
            "name_en": p.name_en,
            "name_ar": p.name_ar,
            "category": p.category,
            "is_active": p.is_active,
            "unit_price": low if low == high else None,
            "price_min": low,
            "price_max": high,
            "currency": rows[0][1] if rows else None,
            "stock": stock.get(p.id, 0),
        })
    return out