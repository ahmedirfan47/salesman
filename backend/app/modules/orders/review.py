"""Checks on orders the WhatsApp AI places, and the customer's order memory.

assess_ai_order(): before an AI order is created, score each line:
  - how well the customer's own words name the product the AI chose
    (app.modules.products.matching), and
  - whether the quantity is far above anything this customer has ordered of
    that product before.
  Lines that fail either check are returned as review reasons; the orders
  service then holds the order as an 'ai_review' escalation instead of
  confirming it. "Shadow mode" (review_all_ai_orders) holds every AI order.

order_memory(): the customer's recent orders and their usual items, so the AI
can handle "same as last time" or "the usual, but 2 more cartons of milk".

correct_held_order(): staff fix a held order's lines (product or quantity),
the corrections are learned as aliases, and the order is approved.
"""
import statistics
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.branches import in_scope
from app.db.models.agent_settings import AgentSettings
from app.db.models.customer import Customer
from app.db.models.escalation import Escalation
from app.db.models.order import Order
from app.db.models.order_item import OrderItem
from app.db.models.product import Product
from app.db.models.product_price import ProductPrice
from app.modules.products import matching

_MEMORY_DAYS = 90


# --- settings -----------------------------------------------------------------

async def get_settings(db: AsyncSession, tenant_id: uuid.UUID) -> AgentSettings:
    row = await db.scalar(select(AgentSettings).where(AgentSettings.tenant_id == tenant_id))
    if row is None:
        row = AgentSettings(
            tenant_id=tenant_id, review_min_confidence=Decimal("0.60"), review_quantity_multiple=4,
            learn_aliases=True, review_all_ai_orders=False,
        )
        db.add(row)
        await db.flush()
    return row


async def update_settings(db: AsyncSession, tenant_id: uuid.UUID, data: dict) -> AgentSettings:
    row = await get_settings(db, tenant_id)
    for key, value in data.items():
        if value is not None and hasattr(row, key):
            setattr(row, key, value)
    if data.get("reorder_template") == "":
        row.reorder_template = None
    if data.get("message_retention_days") == 0:
        row.message_retention_days = None
    await db.commit()
    await db.refresh(row)
    return row


# --- history ------------------------------------------------------------------

def _customer_filter(customer: Customer | None, number_digits: str):
    """Orders belonging to this customer: by account, or by WhatsApp number when unregistered."""
    conds = []
    if customer is not None:
        conds.append(Order.customer_id == customer.id)
    if number_digits:
        conds.append(func.regexp_replace(Order.whatsapp_number, "[^0-9]", "", "g") == number_digits)
    return or_(*conds) if conds else None


async def max_previous_quantities(
    db: AsyncSession, tenant_id: uuid.UUID, customer: Customer | None, number_digits: str, skus: list[str],
) -> dict[str, int]:
    who = _customer_filter(customer, number_digits)
    if who is None or not skus:
        return {}
    rows = await db.execute(
        select(OrderItem.sku, func.max(OrderItem.quantity))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.tenant_id == tenant_id, who, Order.status != "cancelled", OrderItem.sku.in_(skus))
        .group_by(OrderItem.sku)
    )
    return {sku: int(q) for sku, q in rows.all()}


async def order_memory(
    db: AsyncSession, tenant_id: uuid.UUID, customer: Customer | None, number_digits: str, *, recent: int = 3,
) -> dict:
    """Last few orders plus the items this customer usually buys (last 90 days)."""
    who = _customer_filter(customer, number_digits)
    if who is None:
        return {"has_history": False, "recent_orders": [], "usual_items": []}
    orders = list(await db.scalars(
        select(Order)
        .where(Order.tenant_id == tenant_id, who, Order.status != "cancelled")
        .order_by(Order.created_at.desc())
        .limit(recent)
    ))
    since = datetime.now(timezone.utc) - timedelta(days=_MEMORY_DAYS)
    rows = (await db.execute(
        select(OrderItem.sku, OrderItem.product_name, OrderItem.quantity, Order.created_at)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.tenant_id == tenant_id, who, Order.status != "cancelled", Order.created_at >= since)
        .order_by(Order.created_at.desc())
    )).all()

    by_sku: dict[str, dict] = {}
    for sku, name, qty, created in rows:
        entry = by_sku.setdefault(sku, {"sku": sku, "name": name, "quantities": [], "last_ordered": created})
        entry["quantities"].append(int(qty))
    usual = []
    for e in by_sku.values():
        qs = e["quantities"]
        usual.append({
            "sku": e["sku"],
            "name": e["name"],
            "times_ordered": len(qs),
            "typical_quantity": int(statistics.median(qs)),
            "last_quantity": qs[0],
            "last_ordered": e["last_ordered"].date().isoformat(),
        })
    usual.sort(key=lambda u: (-u["times_ordered"], u["name"]))

    return {
        "has_history": bool(orders),
        "recent_orders": [
            {
                "order_number": o.order_number,
                "date": o.created_at.date().isoformat(),
                "status": o.status,
                "total_amount": float(o.total_amount),
                "currency": o.currency,
                "items": [{"sku": i.sku, "name": i.product_name, "quantity": i.quantity} for i in o.items],
            }
            for o in orders
        ],
        "usual_items": usual[:15],
    }


# --- assessing an AI order ----------------------------------------------------------

async def assess_ai_order(
    db: AsyncSession, tenant_id: uuid.UUID, items: list[dict], *,
    customer: Customer | None, number_digits: str,
) -> tuple[list[dict], list[dict]]:
    """Returns (lines, review_reasons).

    lines: one dict per item {sku, quantity, wording, score, product} where score is
    None when the AI gave no customer wording (e.g. the customer typed the SKU).
    review_reasons: [{kind, sku, message, ...}] -- empty means safe to confirm.
    """
    settings = await get_settings(db, tenant_id)
    threshold = float(settings.review_min_confidence)
    skus = [str(i.get("sku", "")).strip() for i in items]
    products = {
        p.sku: p for p in await db.scalars(
            select(Product).where(Product.tenant_id == tenant_id, Product.sku.in_(skus))
        )
    }
    previous = await max_previous_quantities(db, tenant_id, customer, number_digits, skus)

    lines, reasons = [], []
    for item, sku in zip(items, skus):
        qty = int(item.get("quantity") or 0)
        wording = (item.get("customer_wording") or "").strip() or None
        product = products.get(sku)
        score = None
        if product is not None and wording:
            score = await matching.match_score(db, tenant_id, wording, product, customer.id if customer else None)
            if score < threshold:
                reasons.append({
                    "kind": "low_confidence", "sku": sku, "wording": wording, "score": score,
                    "message": f'"{wording}" may not be {product.name_en} ({sku}); match {round(score * 100)}%',
                })
        multiple = settings.review_quantity_multiple
        before = previous.get(sku)
        if multiple and before and qty > before * multiple:
            reasons.append({
                "kind": "unusual_quantity", "sku": sku, "quantity": qty, "previous_max": before,
                "message": f"{sku}: {qty} ordered, the most this customer ordered before was {before}",
            })
        lines.append({"sku": sku, "quantity": qty, "wording": wording, "score": score, "product": product})

    if settings.review_all_ai_orders and not reasons:
        reasons.append({"kind": "shadow_mode", "message": "Every AI order is checked by the team (shadow mode)"})
    return lines, reasons


async def learn_from_confirmed(
    db: AsyncSession, tenant_id: uuid.UUID, lines: list[dict], customer: Customer | None,
) -> int:
    """The customer confirmed these lines: remember their wording for this customer."""
    if customer is None:
        return 0
    settings = await get_settings(db, tenant_id)
    if not settings.learn_aliases:
        return 0
    learned = 0
    for line in lines:
        if line.get("product") is None or not line.get("wording") or line.get("score") is None:
            continue
        if line["score"] >= 0.999:  # already understood exactly
            continue
        if await matching.learn_alias(
            db, tenant_id, line["product"], line["wording"], customer_id=customer.id, source="learned",
        ):
            learned += 1
    await db.commit()
    return learned


# --- staff correction -----------------------------------------------------------------

async def correct_held_order(
    db: AsyncSession, tenant_id: uuid.UUID, escalation_id: uuid.UUID, items: list[dict], *,
    note: str | None = None, actor_id: uuid.UUID | None = None, scope: uuid.UUID | None = None,
) -> Escalation:
    """Replace a held order's lines with the corrected ones, learn the corrections,
    then approve it (stock is taken as for any approval)."""
    from app.modules.orders import service as orders  # avoid an import cycle

    esc = await db.scalar(select(Escalation).where(Escalation.id == escalation_id, Escalation.tenant_id == tenant_id))
    if esc is None or not in_scope(scope, esc.branch_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escalation not found")
    if esc.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "Escalation already resolved")
    order = await db.scalar(select(Order).where(Order.id == esc.order_id)) if esc.order_id else None
    if order is None or order.status != "requires_human_review":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a held order can be corrected")
    if not items:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Add at least one line, or reject the order")

    customer = await db.get(Customer, order.customer_id) if order.customer_id else None
    settings = await get_settings(db, tenant_id)

    new_lines = []
    for line in items:
        sku = str(line["sku"]).strip()
        qty = int(line["quantity"])
        if qty <= 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Quantity for {sku} must be above zero")
        row = (await db.execute(
            select(Product, ProductPrice)
            .join(ProductPrice, ProductPrice.product_id == Product.id)
            .where(
                Product.tenant_id == tenant_id, Product.sku == sku,
                ProductPrice.branch_id == order.branch_id, ProductPrice.effective_to.is_(None),
            )
        )).first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No active price for SKU '{sku}' at this branch")
        new_lines.append((row[0], row[1], qty, (line.get("wording") or "").strip() or None))

    before = {i.sku: i.quantity for i in order.items if not i.is_free}
    after: dict[str, int] = {}
    for product, _, qty, _ in new_lines:
        after[product.sku] = after.get(product.sku, 0) + qty
    lines_changed = sum(1 for sku in set(before) | set(after) if before.get(sku) != after.get(sku))

    from app.modules.deals import service as deals  # the customer's prices and deals apply as on any order

    quotes, free = await deals.quote(db, tenant_id, order.branch_id, customer.id if customer else None,
                                     [(product.id, qty, Decimal(str(price.unit_price))) for product, price, qty, _ in new_lines])
    for item in list(order.items):
        order.items.remove(item)
    await db.flush()
    total = Decimal("0")
    for (product, price, qty, _), q in zip(new_lines, quotes):
        line_total = q.unit_price * qty
        total += line_total
        order.items.append(OrderItem(
            tenant_id=tenant_id, product_id=product.id, sku=product.sku, product_name=product.name_en,
            quantity=qty, unit_price=q.unit_price, unit_cost=product.cost_price, line_total=line_total,
            available_at_order=None, list_price=q.list_price, price_source=q.source, promotion_id=q.promotion_id,
        ))
    for f in free:
        product = await db.get(Product, f.product_id)
        order.items.append(OrderItem(
            tenant_id=tenant_id, product_id=product.id, sku=product.sku, product_name=product.name_en,
            quantity=f.quantity, unit_price=Decimal("0.00"), unit_cost=product.cost_price, line_total=Decimal("0.00"),
            available_at_order=None, price_source="promotion", promotion_id=f.promotion_id, is_free=True,
        ))
    order.total_amount = total
    order.price_list_id = new_lines[0][1].price_list_id

    learned = 0
    if settings.learn_aliases:
        for product, _, _, wording in new_lines:
            if wording and await matching.learn_alias(
                db, tenant_id, product, wording, customer_id=customer.id if customer else None,
                source="correction", actor_id=actor_id,
            ):
                learned += 1
    esc.context = {**(esc.context or {}), "corrected": True, "aliases_learned": learned,
                   "lines_before": len(before), "lines_changed": lines_changed}
    await db.commit()

    return await orders.resolve_escalation(
        db, tenant_id, escalation_id, approve=True,
        note=note or "Corrected by the team and approved", actor_id=actor_id, scope=scope,
    )
