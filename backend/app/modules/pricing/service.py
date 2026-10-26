"""Pricing / price-list versioning service.

Each branch has its own price list and its own stock: a list is uploaded for
one branch, and activating it changes only that branch's prices and stock.

Core rule: uploading a new price list NEVER overwrites history.
- Each upload is a new PriceList row with an incrementing version (per branch).
- Its price lines are stored as 'parked' ProductPrice rows (a zero-width
  time window) carrying the price + the sheet's declared quantity.
- Activating a list, in ONE transaction:
    1. closes the branch's currently-active price rows (effective_to = now),
    2. marks the branch's old active list 'superseded',
    3. opens this list's parked rows (effective_from = now, effective_to = NULL),
    4. sets the branch's inventory to the sheet quantities, writing immutable ledger rows,
    5. copies any costs from the sheet onto the products (cost_price), so
       orders from now on snapshot that cost for margin analytics,
    6. marks this list 'active'.
"""
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.branches import default_branch
from app.db.models.inventory import Inventory
from app.db.models.inventory_transaction import InventoryTransaction
from app.db.models.price_list import PriceList
from app.db.models.product import Product
from app.db.models.product_price import ProductPrice
from app.schemas.pricing import PriceLineIn, PriceListCreate


async def _next_version(db: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID) -> int:
    current = await db.scalar(
        select(func.max(PriceList.version)).where(
            PriceList.tenant_id == tenant_id, PriceList.branch_id == branch_id
        )
    )
    return (current or 0) + 1


async def _resolve_product(db: AsyncSession, tenant_id: uuid.UUID, line: PriceLineIn) -> Product:
    product = await db.scalar(
        select(Product).where(Product.tenant_id == tenant_id, Product.sku == line.sku)
    )
    if product:
        return product
    product = Product(
        tenant_id=tenant_id,
        sku=line.sku,
        name_en=line.name_en or line.sku,
        name_ar=line.name_ar,
    )
    db.add(product)
    await db.flush()
    return product


async def create_price_list(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: PriceListCreate,
    *,
    branch_id: uuid.UUID | None = None,
    uploaded_by: uuid.UUID | None = None,
    file_hash: str | None = None,
) -> PriceList:
    """Create a DRAFT (pending) price list plus parked price lines. Not yet active."""
    now = datetime.now(timezone.utc)
    if branch_id is None:
        branch_id = (await default_branch(db, tenant_id)).id
    version = await _next_version(db, tenant_id, branch_id)
    price_list = PriceList(
        tenant_id=tenant_id,
        branch_id=branch_id,
        version=version,
        source_filename=data.source_filename,
        file_hash=file_hash,
        status="pending",
        uploaded_by=uploaded_by,
    )
    db.add(price_list)
    await db.flush()

    seen: set[str] = set()
    for line in data.lines:
        if line.sku in seen:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Duplicate SKU in upload: {line.sku}")
        seen.add(line.sku)
        product = await _resolve_product(db, tenant_id, line)
        db.add(
            ProductPrice(
                tenant_id=tenant_id,
                branch_id=branch_id,
                product_id=product.id,
                price_list_id=price_list.id,
                unit_price=line.unit_price,
                currency=line.currency,
                sheet_quantity=line.quantity,
                unit_cost=line.unit_cost,
                effective_from=now,
                effective_to=now,
            )
        )

    await db.commit()
    await db.refresh(price_list)
    return price_list


async def activate_price_list(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    price_list_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
) -> PriceList:
    now = datetime.now(timezone.utc)

    price_list = await db.scalar(
        select(PriceList).where(PriceList.id == price_list_id, PriceList.tenant_id == tenant_id)
    )
    if not price_list:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price list not found")
    if price_list.status == "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Price list is already active")
    if price_list.status == "superseded":
        raise HTTPException(status.HTTP_409_CONFLICT, "Price list was already superseded")
    branch_id = price_list.branch_id

    for p in await db.scalars(
        select(ProductPrice).where(
            ProductPrice.tenant_id == tenant_id,
            ProductPrice.branch_id == branch_id,
            ProductPrice.effective_to.is_(None),
        )
    ):
        p.effective_to = now

    prev_active = await db.scalar(
        select(PriceList).where(
            PriceList.tenant_id == tenant_id,
            PriceList.branch_id == branch_id,
            PriceList.status == "active",
        )
    )
    if prev_active:
        prev_active.status = "superseded"
        prev_active.superseded_at = now

    for p in await db.scalars(
        select(ProductPrice).where(
            ProductPrice.tenant_id == tenant_id,
            ProductPrice.price_list_id == price_list.id,
        )
    ):
        p.effective_from = now
        p.effective_to = None
        if p.unit_cost is not None:
            # Only rows that carry a cost update it; a sheet without a Cost
            # column never wipes costs entered on the Analytics page.
            product = await db.get(Product, p.product_id)
            if product is not None and product.tenant_id == tenant_id:
                product.cost_price = p.unit_cost
                product.cost_currency = p.currency
        if p.sheet_quantity is not None:
            await _set_inventory(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                product_id=p.product_id,
                new_quantity=p.sheet_quantity,
                reason="price_list_upload",
                reference_id=price_list.id,
                actor_id=actor_id,
            )

    price_list.status = "active"
    price_list.activated_at = now

    await db.commit()
    await db.refresh(price_list)
    return price_list


async def _set_inventory(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    branch_id: uuid.UUID,
    product_id: uuid.UUID,
    new_quantity: int,
    reason: str,
    reference_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> None:
    inv = await db.scalar(
        select(Inventory).where(
            Inventory.tenant_id == tenant_id,
            Inventory.branch_id == branch_id,
            Inventory.product_id == product_id,
        )
    )
    before = inv.quantity_on_hand if inv else 0
    if inv is None:
        inv = Inventory(tenant_id=tenant_id, branch_id=branch_id, product_id=product_id,
                        quantity_on_hand=new_quantity)
        db.add(inv)
    else:
        inv.quantity_on_hand = new_quantity

    db.add(
        InventoryTransaction(
            tenant_id=tenant_id,
            branch_id=branch_id,
            product_id=product_id,
            delta=new_quantity - before,
            quantity_before=before,
            quantity_after=new_quantity,
            reason=reason,
            reference_type="price_list" if reason == "price_list_upload" else None,
            reference_id=reference_id,
            created_by=actor_id,
        )
    )


async def list_price_lists(
    db: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID | None = None
) -> list[PriceList]:
    q = select(PriceList).where(PriceList.tenant_id == tenant_id)
    if branch_id is not None:
        q = q.where(PriceList.branch_id == branch_id)
    return list(await db.scalars(q.order_by(PriceList.created_at.desc())))


async def get_current_price(
    db: AsyncSession, tenant_id: uuid.UUID, sku: str, branch_id: uuid.UUID
) -> dict | None:
    """Today's price and stock for a SKU at one branch."""
    row = await db.execute(
        select(Product, ProductPrice, Inventory, PriceList)
        .join(ProductPrice, ProductPrice.product_id == Product.id)
        .join(PriceList, PriceList.id == ProductPrice.price_list_id)
        .outerjoin(
            Inventory,
            (Inventory.product_id == Product.id) & (Inventory.branch_id == ProductPrice.branch_id),
        )
        .where(
            Product.tenant_id == tenant_id,
            Product.sku == sku,
            ProductPrice.branch_id == branch_id,
            ProductPrice.effective_to.is_(None),
        )
    )
    result = row.first()
    if not result:
        return None
    product, price, inv, plist = result
    return {
        "product_id": product.id,
        "sku": product.sku,
        "name_en": product.name_en,
        "unit_price": price.unit_price,
        "currency": price.currency,
        "quantity_on_hand": inv.quantity_on_hand if inv else 0,
        "price_list_version": plist.version,
        "effective_from": price.effective_from,
    }


async def price_history(
    db: AsyncSession, tenant_id: uuid.UUID, product_id: uuid.UUID, branch_id: uuid.UUID | None = None
) -> list[ProductPrice]:
    q = select(ProductPrice).where(
        ProductPrice.tenant_id == tenant_id, ProductPrice.product_id == product_id
    )
    if branch_id is not None:
        q = q.where(ProductPrice.branch_id == branch_id)
    return list(await db.scalars(q.order_by(ProductPrice.effective_from.desc())))