"""Prices and stock from an ERP, the same way for every connector.

A connector only reads its ERP and returns a Catalog: the products (SKU,
names, cost) and, for each branch linked to a warehouse, one price-and-stock
line per product. This module then

- apply(): updates product names and costs, and gives each branch a new price
  list version when any price changed (stock alone is set in place, through
  the inventory ledger), or
- preview(): says what apply() would change without writing anything -- the
  "dry run" the business uses before switching a connection on.

Stock Salesman has promised on orders not yet sent to the ERP is taken off
what the ERP reports, so the same units are never sold twice.
"""
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import String, and_, cast, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.branch import Branch
from app.db.models.integration import IntegrationConnection, IntegrationLink
from app.db.models.inventory import Inventory
from app.db.models.order import Order
from app.db.models.order_item import OrderItem
from app.db.models.product import Product
from app.db.models.product_price import ProductPrice
from app.modules.integrations import store
from app.modules.integrations.base import CENT, PENDING_ORDER, Result
from app.modules.pricing import service as pricing
from app.schemas.pricing import PriceLineIn, PriceListCreate


@dataclass
class CatalogProduct:
    sku: str
    external_id: str
    name_en: str
    name_ar: str | None = None
    cost: Decimal | None = None


@dataclass
class Catalog:
    products: list[CatalogProduct]
    branches: list[tuple[Branch, list[PriceLineIn]]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cost_currency: str | None = None
    empty_message: str = "No branch is linked to a warehouse."
    source: str = "ERP sync"


async def pending(db: AsyncSession, conn: IntegrationConnection, branch_id: uuid.UUID) -> dict[str, int]:
    """Stock Salesman has promised that the ERP doesn't know about yet (orders not sent so far)."""
    sent = exists().where(and_(
        IntegrationLink.connection_id == conn.id, IntegrationLink.entity == "order",
        IntegrationLink.local_key == cast(Order.id, String),
    ))
    q = (
        select(OrderItem.sku, func.sum(OrderItem.quantity))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.tenant_id == conn.tenant_id, Order.branch_id == branch_id, Order.status.in_(PENDING_ORDER), ~sent)
        .group_by(OrderItem.sku)
    )
    if conn.connected_at is not None:
        q = q.where(Order.confirmed_at >= conn.connected_at)
    return {sku: int(qty or 0) for sku, qty in await db.execute(q)}


async def mapped_branches(db: AsyncSession, conn: IntegrationConnection) -> list[tuple[Branch, dict]]:
    """Active branches with a warehouse chosen, in the order of the mapping."""
    branches = {b.id: b for b in await db.scalars(
        select(Branch).where(Branch.tenant_id == conn.tenant_id, Branch.is_active.is_(True))
    )}
    out = []
    for branch_id, mapping in ((conn.settings or {}).get("branches") or {}).items():
        branch = branches.get(uuid.UUID(branch_id))
        if branch is not None and (mapping or {}).get("warehouse_id"):
            out.append((branch, mapping))
    return out


async def _current(db: AsyncSession, conn: IntegrationConnection, branch: Branch):
    rows = await db.execute(
        select(Product.sku, ProductPrice.unit_price, ProductPrice.currency)
        .join(ProductPrice, ProductPrice.product_id == Product.id)
        .where(ProductPrice.tenant_id == conn.tenant_id, ProductPrice.branch_id == branch.id, ProductPrice.effective_to.is_(None))
    )
    prices = {sku: (Decimal(str(price)).quantize(CENT), cur) for sku, price, cur in rows}
    stock = dict((await db.execute(
        select(Product.sku, Inventory.quantity_on_hand).join(Product, Product.id == Inventory.product_id)
        .where(Inventory.tenant_id == conn.tenant_id, Inventory.branch_id == branch.id)
    )).all())
    return prices, stock


async def _apply_branch(db: AsyncSession, conn: IntegrationConnection, branch: Branch, lines: list[PriceLineIn],
                        source: str) -> dict:
    current, stock = await _current(db, conn, branch)
    wanted = {ln.sku: (Decimal(str(ln.unit_price)).quantize(CENT), ln.currency) for ln in lines}
    if current != wanted:
        plist = await pricing.create_price_list(db, conn.tenant_id, PriceListCreate(source_filename=source, lines=lines),
                                                branch_id=branch.id)
        await pricing.activate_price_list(db, conn.tenant_id, plist.id)
        return {"prices_changed": True, "stock_changed": len(lines)}
    products = {p.sku: p for p in await db.scalars(
        select(Product).where(Product.tenant_id == conn.tenant_id, Product.sku.in_(list(wanted)))
    )}
    changed = 0
    for ln in lines:
        product = products.get(ln.sku)
        if product is not None and stock.get(ln.sku, 0) != ln.quantity:
            await pricing._set_inventory(db, tenant_id=conn.tenant_id, branch_id=branch.id, product_id=product.id,
                                         new_quantity=ln.quantity, reason="erp_sync")
            changed += 1
    await db.commit()
    return {"prices_changed": False, "stock_changed": changed}


async def apply(db: AsyncSession, conn: IntegrationConnection, cat: Catalog) -> Result:
    # products: names and costs follow the ERP
    existing = {p.sku: p for p in await db.scalars(
        select(Product).where(Product.tenant_id == conn.tenant_id, Product.sku.in_([p.sku for p in cat.products]))
    )}
    for item in cat.products:
        product = existing.get(item.sku)
        if product is not None:
            product.name_en = item.name_en[:255]
            if item.name_ar and item.name_ar != item.name_en:
                product.name_ar = item.name_ar[:255]
            if item.cost:
                product.cost_price = Decimal(str(item.cost)).quantize(CENT)
                product.cost_currency = cat.cost_currency
            product.is_active = True
        link = await store.get_link(db, conn, "product", item.sku)
        if link is None or link.external_id != str(item.external_id):
            await store.save_link(db, conn, "product", item.sku, item.external_id, external_ref=item.name_en[:120])
    await db.commit()

    summary = []
    for branch, lines in cat.branches:
        applied = await _apply_branch(db, conn, branch, lines, cat.source)
        summary.append({"branch": branch.name, "products": len(lines), **applied})
    message = "; ".join(
        f"{x['branch']}: {x['products']} products, " + ("prices updated" if x["prices_changed"] else f"{x['stock_changed']} stock change(s)")
        for x in summary
    ) or cat.empty_message
    return Result("warning" if cat.notes else "ok", " ".join([message.rstrip(".") + "."] + cat.notes))


async def preview(db: AsyncSession, conn: IntegrationConnection, cat: Catalog) -> dict:
    """What apply() would change, without changing anything."""
    known = set(await db.scalars(
        select(Product.sku).where(Product.tenant_id == conn.tenant_id, Product.sku.in_([p.sku for p in cat.products]))
    ))
    branches = []
    for branch, lines in cat.branches:
        prices, stock = await _current(db, conn, branch)
        wanted = {ln.sku: ln for ln in lines}
        changes = []
        for ln in lines:
            now = prices.get(ln.sku)
            new_price = Decimal(str(ln.unit_price)).quantize(CENT)
            if now is None:
                changes.append({"sku": ln.sku, "kind": "new", "price": new_price, "quantity": ln.quantity})
            elif now[0] != new_price or now[1] != ln.currency:
                changes.append({"sku": ln.sku, "kind": "price", "from": now[0], "to": new_price})
            elif stock.get(ln.sku, 0) != ln.quantity:
                changes.append({"sku": ln.sku, "kind": "stock", "from": stock.get(ln.sku, 0), "to": ln.quantity})
        dropped = sorted(sku for sku in prices if sku not in wanted)
        branches.append({
            "branch": branch.name,
            "products": len(lines),
            "new": sum(1 for c in changes if c["kind"] == "new"),
            "price_changes": sum(1 for c in changes if c["kind"] == "price"),
            "stock_changes": sum(1 for c in changes if c["kind"] == "stock"),
            # sold in Salesman today but not found in the ERP: they would leave this branch's price list
            "not_in_erp": dropped[:50],
            "not_in_erp_count": len(dropped),
            "examples": changes[:15],
        })
    return {
        "products": len(cat.products),
        "new_products": sum(1 for p in cat.products if p.sku not in known),
        "branches": branches,
        "notes": cat.notes,
        "message": None if branches else cat.empty_message,
    }
