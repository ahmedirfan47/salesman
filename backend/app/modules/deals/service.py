"""Customer prices, promotions and free goods.

How a line is priced (quote()):
1. Start from the branch list price.
2. Customer price: the customer's own price for the product, if one applies
   today -- this branch's row before an all-branch row, then the highest
   minimum quantity the line reaches.
3. Price deals (percent_off, fixed_price) that apply today to this product,
   branch, customer and quantity.
4. The customer pays the LOWEST of the list price, their own price and every
   price deal. Deals don't stack, so a 10% deal never cuts a price that was
   already agreed lower.
5. Free goods: the single most generous buy_get deal for the product adds
   floor(qty / buy) x free units at price 0, as a separate order line. Free
   units never take stock the paid lines need; if stock runs short, fewer are
   given and the order notes it.

Every order line keeps the list price, the price charged and where it came
from (list | customer | promotion), so margins and deal costs can be reported.
"""
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.customer import Customer
from app.db.models.deals import CustomerPrice, Promotion
from app.db.models.product import Product
from app.modules.accounts import service as accounts

CENT = Decimal("0.01")
KINDS = ("percent_off", "fixed_price", "buy_get")


def _money(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Quote:
    unit_price: Decimal
    list_price: Decimal
    source: str = "list"                     # list | customer | promotion
    promotion_id: uuid.UUID | None = None
    promotion_name: str | None = None


@dataclass
class Free:
    product_id: uuid.UUID
    quantity: int
    promotion_id: uuid.UUID
    promotion_name: str


@dataclass
class _Deals:
    prices: list[CustomerPrice] = field(default_factory=list)
    promos: list[Promotion] = field(default_factory=list)


def _valid(start: date | None, end: date | None, today: date) -> bool:
    return (start is None or start <= today) and (end is None or end >= today)


async def _load(db: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID, customer_id: uuid.UUID | None,
                product_ids: list[uuid.UUID]) -> _Deals:
    out = _Deals()
    if not product_ids:
        return out
    if customer_id is not None:
        out.prices = list(await db.scalars(select(CustomerPrice).where(
            CustomerPrice.tenant_id == tenant_id, CustomerPrice.customer_id == customer_id,
            CustomerPrice.product_id.in_(product_ids),
            or_(CustomerPrice.branch_id.is_(None), CustomerPrice.branch_id == branch_id),
        )))
    cust = Promotion.customer_id.is_(None) if customer_id is None else \
        or_(Promotion.customer_id.is_(None), Promotion.customer_id == customer_id)
    out.promos = list(await db.scalars(select(Promotion).where(
        Promotion.tenant_id == tenant_id, Promotion.is_active.is_(True), Promotion.product_id.in_(product_ids),
        or_(Promotion.branch_id.is_(None), Promotion.branch_id == branch_id), cust,
    )))
    return out


def _price(deals: _Deals, product_id: uuid.UUID, qty: int, list_price: Decimal, today: date) -> Quote:
    best = Quote(unit_price=_money(list_price), list_price=_money(list_price))
    rows = [r for r in deals.prices if r.product_id == product_id and qty >= r.min_quantity
            and _valid(r.valid_from, r.valid_to, today)]
    if rows:
        row = sorted(rows, key=lambda r: (r.branch_id is not None, r.min_quantity), reverse=True)[0]
        if _money(row.unit_price) < best.unit_price:
            best = Quote(unit_price=_money(row.unit_price), list_price=best.list_price, source="customer")
    for p in deals.promos:
        if p.product_id != product_id or p.kind == "buy_get" or qty < p.min_quantity \
                or not _valid(p.starts_on, p.ends_on, today):
            continue
        if p.kind == "percent_off" and p.percent_off:
            price = _money(Decimal(str(list_price)) * (Decimal(100) - Decimal(str(p.percent_off))) / Decimal(100))
        elif p.kind == "fixed_price" and p.fixed_price is not None:
            price = _money(p.fixed_price)
        else:
            continue
        if price < best.unit_price:
            best = Quote(unit_price=price, list_price=best.list_price, source="promotion", promotion_id=p.id,
                         promotion_name=p.name)
    return best


def _free(deals: _Deals, product_id: uuid.UUID, qty: int, today: date) -> Free | None:
    best = None
    for p in deals.promos:
        if p.product_id != product_id or p.kind != "buy_get" or qty < p.min_quantity \
                or not p.buy_quantity or not p.free_quantity or not _valid(p.starts_on, p.ends_on, today):
            continue
        n = (qty // p.buy_quantity) * p.free_quantity
        if n > 0 and (best is None or n > best.quantity):
            best = Free(product_id=p.free_product_id or p.product_id, quantity=n, promotion_id=p.id, promotion_name=p.name)
    return best


async def quote(db: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID, customer_id: uuid.UUID | None,
                lines: list[tuple[uuid.UUID, int, Decimal]], today: date | None = None) -> tuple[list[Quote], list[Free]]:
    """lines: (product_id, quantity, list price). Returns one Quote per line, and the free goods earned."""
    today = today or await accounts._today(db, tenant_id)
    deals = await _load(db, tenant_id, branch_id, customer_id, list({pid for pid, _, _ in lines}))
    quotes = [_price(deals, pid, qty, price, today) for pid, qty, price in lines]
    totals: dict[uuid.UUID, int] = {}
    for pid, qty, _ in lines:
        totals[pid] = totals.get(pid, 0) + qty
    free = [f for f in (_free(deals, pid, qty, today) for pid, qty in totals.items()) if f]
    return quotes, free


# ---- managing deals ---------------------------------------------------------------------------

async def _product(db: AsyncSession, tenant_id: uuid.UUID, *, product_id=None, sku=None) -> Product:
    q = select(Product).where(Product.tenant_id == tenant_id)
    q = q.where(Product.id == product_id) if product_id else q.where(Product.sku == sku)
    product = await db.scalar(q)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Product {sku or product_id} not found")
    return product


async def _customer(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> Customer:
    c = await db.scalar(select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id))
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return c


def _dates(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The end date is before the start date")


async def list_customer_prices(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID | None = None) -> list[dict]:
    q = (select(CustomerPrice, Product.sku, Product.name_en, Customer.name, Customer.company)
         .join(Product, Product.id == CustomerPrice.product_id).join(Customer, Customer.id == CustomerPrice.customer_id)
         .where(CustomerPrice.tenant_id == tenant_id))
    if customer_id:
        q = q.where(CustomerPrice.customer_id == customer_id)
    rows = await db.execute(q.order_by(Customer.name, Product.sku, CustomerPrice.min_quantity))
    return [{**_row(cp), "sku": sku, "product_name": pname, "customer_name": company or cname}
            for cp, sku, pname, cname, company in rows]


def _row(obj) -> dict:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


async def save_customer_price(db: AsyncSession, tenant_id: uuid.UUID, data: dict, price_id: uuid.UUID | None = None) -> dict:
    await _customer(db, tenant_id, data["customer_id"])
    product = await _product(db, tenant_id, sku=data["sku"])
    _dates(data.get("valid_from"), data.get("valid_to"))
    if price_id:
        row = await db.scalar(select(CustomerPrice).where(CustomerPrice.id == price_id, CustomerPrice.tenant_id == tenant_id))
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    else:
        row = await db.scalar(select(CustomerPrice).where(
            CustomerPrice.tenant_id == tenant_id, CustomerPrice.customer_id == data["customer_id"],
            CustomerPrice.product_id == product.id, CustomerPrice.min_quantity == data.get("min_quantity", 1),
            CustomerPrice.branch_id.is_(None) if data.get("branch_id") is None else CustomerPrice.branch_id == data["branch_id"],
        ))
        if row is None:
            row = CustomerPrice(tenant_id=tenant_id)
            db.add(row)
    row.customer_id, row.product_id, row.branch_id = data["customer_id"], product.id, data.get("branch_id")
    row.unit_price = _money(data["unit_price"])
    row.min_quantity = int(data.get("min_quantity") or 1)
    row.valid_from, row.valid_to, row.note = data.get("valid_from"), data.get("valid_to"), data.get("note")
    await db.commit()
    return next(r for r in await list_customer_prices(db, tenant_id, row.customer_id) if r["id"] == row.id)


async def delete_customer_price(db: AsyncSession, tenant_id: uuid.UUID, price_id: uuid.UUID) -> None:
    row = await db.scalar(select(CustomerPrice).where(CustomerPrice.id == price_id, CustomerPrice.tenant_id == tenant_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await db.delete(row)
    await db.commit()


async def list_promotions(db: AsyncSession, tenant_id: uuid.UUID) -> list[dict]:
    rows = list(await db.scalars(select(Promotion).where(Promotion.tenant_id == tenant_id)
                                 .order_by(Promotion.is_active.desc(), Promotion.created_at.desc())))
    pids = {r.product_id for r in rows} | {r.free_product_id for r in rows if r.free_product_id}
    products = {p.id: p for p in await db.scalars(select(Product).where(Product.id.in_(pids)))} if pids else {}
    cids = {r.customer_id for r in rows if r.customer_id}
    customers = {c.id: c for c in await db.scalars(select(Customer).where(Customer.id.in_(cids)))} if cids else {}
    today = await accounts._today(db, tenant_id)
    out = []
    for r in rows:
        p, fp, c = products.get(r.product_id), products.get(r.free_product_id), customers.get(r.customer_id)
        out.append({**_row(r), "sku": p.sku if p else None, "product_name": p.name_en if p else None,
                    "free_sku": fp.sku if fp else None, "customer_name": (c.company or c.name) if c else None,
                    "live": r.is_active and _valid(r.starts_on, r.ends_on, today), "summary": describe(r, p, fp)})
    return out


def describe(p: Promotion, product: Product | None = None, free_product: Product | None = None) -> str:
    name = product.name_en if product else "this product"
    min_q = f" on {p.min_quantity}+" if p.min_quantity > 1 else ""
    if p.kind == "percent_off":
        return f"{format(Decimal(str(p.percent_off)).normalize(), 'f')}% off {name}{min_q}"
    if p.kind == "fixed_price":
        return f"{name} at {_money(p.fixed_price)}{min_q}"
    other = f" {free_product.name_en}" if free_product and free_product.id != p.product_id else ""
    return f"Buy {p.buy_quantity} {name}, get {p.free_quantity}{other} free"


async def save_promotion(db: AsyncSession, tenant_id: uuid.UUID, data: dict, promo_id: uuid.UUID | None = None) -> dict:
    kind = data["kind"]
    if kind not in KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose percent_off, fixed_price or buy_get")
    product = await _product(db, tenant_id, sku=data["sku"])
    free_product = await _product(db, tenant_id, sku=data["free_sku"]) if data.get("free_sku") else None
    if data.get("customer_id"):
        await _customer(db, tenant_id, data["customer_id"])
    _dates(data.get("starts_on"), data.get("ends_on"))
    pct, fixed, buy, free = data.get("percent_off"), data.get("fixed_price"), data.get("buy_quantity"), data.get("free_quantity")
    if kind == "percent_off" and not (pct and 0 < Decimal(str(pct)) < 100):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter a percentage between 0 and 100")
    if kind == "fixed_price" and (fixed is None or Decimal(str(fixed)) < 0):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter the deal price")
    if kind == "buy_get" and not (buy and free and int(buy) >= 1 and int(free) >= 1):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter how many to buy and how many are free")
    if promo_id:
        row = await db.scalar(select(Promotion).where(Promotion.id == promo_id, Promotion.tenant_id == tenant_id))
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    else:
        row = Promotion(tenant_id=tenant_id)
        db.add(row)
    row.name = (data.get("name") or "").strip()[:120] or describe(
        Promotion(kind=kind, percent_off=pct, fixed_price=fixed, buy_quantity=buy, free_quantity=free,
                  min_quantity=int(data.get("min_quantity") or 1), product_id=product.id), product, free_product)[:120]
    row.kind, row.product_id = kind, product.id
    row.branch_id, row.customer_id = data.get("branch_id"), data.get("customer_id")
    row.min_quantity = int(data.get("min_quantity") or 1)
    row.percent_off = Decimal(str(pct)) if kind == "percent_off" else None
    row.fixed_price = _money(fixed) if kind == "fixed_price" else None
    row.buy_quantity = int(buy) if kind == "buy_get" else None
    row.free_quantity = int(free) if kind == "buy_get" else None
    row.free_product_id = free_product.id if (kind == "buy_get" and free_product) else None
    row.starts_on, row.ends_on = data.get("starts_on"), data.get("ends_on")
    row.is_active = bool(data.get("is_active", True))
    await db.commit()
    return next(r for r in await list_promotions(db, tenant_id) if r["id"] == row.id)


async def delete_promotion(db: AsyncSession, tenant_id: uuid.UUID, promo_id: uuid.UUID) -> None:
    row = await db.scalar(select(Promotion).where(Promotion.id == promo_id, Promotion.tenant_id == tenant_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await db.delete(row)
    await db.commit()


async def preview(db: AsyncSession, tenant_id: uuid.UUID, *, branch_id: uuid.UUID, customer_id: uuid.UUID | None,
                  sku: str, quantity: int) -> dict:
    """What this customer would pay for this line today."""
    from app.modules.pricing import service as pricing

    current = await pricing.get_current_price(db, tenant_id, sku, branch_id)
    product = await _product(db, tenant_id, sku=sku)
    quotes, free = await quote(db, tenant_id, branch_id, customer_id,
                               [(product.id, quantity, Decimal(str(current["unit_price"])))])
    q = quotes[0]
    out = {"sku": sku, "quantity": quantity, "list_price": q.list_price, "unit_price": q.unit_price, "source": q.source,
           "promotion": q.promotion_name, "line_total": _money(q.unit_price * quantity), "free": []}
    for f in free:
        fp = await _product(db, tenant_id, product_id=f.product_id)
        out["free"].append({"sku": fp.sku, "name": fp.name_en, "quantity": f.quantity, "promotion": f.promotion_name})
    return out


async def offers_for(db: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID, customer_id: uuid.UUID | None,
                     product_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """Live deals per product, in words, for the AI to mention."""
    today = await accounts._today(db, tenant_id)
    deals = await _load(db, tenant_id, branch_id, customer_id, product_ids)
    products = {p.id: p for p in await db.scalars(select(Product).where(
        Product.id.in_(list(product_ids) + [p.free_product_id for p in deals.promos if p.free_product_id])))}
    out: dict[uuid.UUID, list[str]] = {}
    for p in deals.promos:
        if _valid(p.starts_on, p.ends_on, today):
            out.setdefault(p.product_id, []).append(describe(p, products.get(p.product_id), products.get(p.free_product_id)))
    return out
