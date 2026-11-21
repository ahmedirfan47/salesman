"""Orders service -- the transactional heart of Salesman.

create_order():
  - resolves each line to a product + its CURRENT price (effective_to IS NULL)
  - locks the inventory rows (SELECT ... FOR UPDATE) so concurrent orders
    cannot oversell the last units
  - if every line has enough stock -> CONFIRM atomically:
        decrement inventory via the immutable ledger,
        snapshot unit prices, set status='confirmed'
  - if any line is short -> status='requires_human_review' + create an
    Escalation row (no stock is touched). A human approves/rejects later.

Hard rule: an order is NEVER confirmed for a quantity beyond available stock
without explicit human approval.

Credit control works the same way: an order for a customer who is on hold,
has an invoice overdue past the grace period, or would go over their credit
limit is held with a 'credit' escalation, even when everything is in stock.
Invoices are issued by the accounts module (on confirmation or delivery).

Every order belongs to one branch: it is priced from that branch's price list
and takes stock from that branch's inventory.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.branches import default_branch, get_branch, in_scope
from app.db.models.customer import Customer
from app.db.models.escalation import Escalation
from app.db.models.inventory import Inventory
from app.db.models.inventory_transaction import InventoryTransaction
from app.db.models.order import Order
from app.db.models.order_event import OrderEvent
from app.db.models.order_item import OrderItem
from app.db.models.product import Product
from app.db.models.product_price import ProductPrice
from app.modules.accounts import service as accounts
from app.modules.deals import service as deals
from app.modules.integrations import hooks as erp
from app.modules.notifications import service as notifications
from app.modules.printing import service as printing_service
from app.schemas.order import OrderCreate


async def _generate_order_number(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    count = await db.scalar(
        select(func.count(Order.id)).where(Order.tenant_id == tenant_id)
    )
    return f"ORD-{(count or 0) + 1:05d}"


async def _current_price_row(
    db: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID, sku: str
) -> tuple[Product, ProductPrice] | None:
    row = await db.execute(
        select(Product, ProductPrice)
        .join(ProductPrice, ProductPrice.product_id == Product.id)
        .where(
            Product.tenant_id == tenant_id,
            Product.sku == sku,
            ProductPrice.branch_id == branch_id,
            ProductPrice.effective_to.is_(None),
        )
    )
    return row.first()


async def _order_branch(
    db: AsyncSession, tenant_id: uuid.UUID, requested: uuid.UUID | None,
    customer: Customer | None, scope: uuid.UUID | None,
) -> uuid.UUID:
    """Explicit branch, else the customer's branch, else the caller's branch, else the default."""
    if requested is not None:
        await get_branch(db, tenant_id, requested)
        branch_id = requested
    elif customer is not None:
        branch_id = customer.branch_id
    elif scope is not None:
        branch_id = scope
    else:
        branch_id = (await default_branch(db, tenant_id)).id
    if not in_scope(scope, branch_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "That branch is outside your access")
    return branch_id


def _item(order: Order, tenant_id: uuid.UUID, e: dict, line_total: Decimal) -> OrderItem:
    return OrderItem(
        order_id=order.id,
        tenant_id=tenant_id,
        product_id=e["product"].id,
        sku=e["product"].sku,
        product_name=e["product"].name_en,
        quantity=e["quantity"],
        unit_price=e["unit_price"],
        unit_cost=e["product"].cost_price,
        line_total=line_total,
        available_at_order=e["available"],
        list_price=e["list_price"],
        price_source=e["price_source"],
        promotion_id=e["promotion_id"],
        is_free=e["free"],
    )


async def create_order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: OrderCreate,
    *,
    actor_id: uuid.UUID | None = None,
    scope: uuid.UUID | None = None,
    review: list[dict] | None = None,
    ai_lines: list[dict] | None = None,
    source: str = "manual",
) -> Order:
    """`review`: reasons the AI's order needs a person to check it (see
    app.modules.orders.review). Any reason holds the order, like a stock or
    credit problem does. `ai_lines`: the customer's own words per line, kept
    on the escalation so staff see what was asked for. `source`: ai when the
    WhatsApp agent placed it (used by the accuracy report).

    Prices: the branch list price, unless the customer has their own price or
    a deal applies (app.modules.deals); free goods from buy-X-get-Y deals are
    added as separate lines at price 0, never taking stock a paid line needs."""
    now = datetime.now(timezone.utc)
    review = review or []

    # 0. if the order is for a known customer, pull their details + zone so the
    #    order is ready for (auto-)assignment. Explicit fields on the request win.
    cust_zone_id = None
    cust_name = data.customer_name
    cust_company = data.customer_company
    cust_whatsapp = data.whatsapp_number
    customer = None
    if getattr(data, "customer_id", None):
        customer = await db.scalar(
            select(Customer).where(
                Customer.id == data.customer_id, Customer.tenant_id == tenant_id
            )
        )
        if not customer:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
        cust_zone_id = customer.zone_id
        cust_name = cust_name or customer.name
        cust_company = cust_company or customer.company
        cust_whatsapp = cust_whatsapp or customer.whatsapp_number

    branch_id = await _order_branch(db, tenant_id, data.branch_id, customer, scope)

    # 1. resolve every line to product + current price, collecting shortfalls
    resolved: list[dict] = []
    shortfalls: list[dict] = []

    for line in data.items:
        found = await _current_price_row(db, tenant_id, branch_id, line.sku)
        if not found:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"No active price for SKU '{line.sku}' at this branch. Cannot price this order.",
            )
        product, price = found

        # lock this branch's inventory row for this product
        inv = await db.scalar(
            select(Inventory)
            .where(
                Inventory.tenant_id == tenant_id,
                Inventory.branch_id == branch_id,
                Inventory.product_id == product.id,
            )
            .with_for_update()
        )
        available = inv.quantity_on_hand if inv else 0

        entry = {
            "product": product,
            "price": price,
            "quantity": line.quantity,
            "available": available,
            "inv": inv,
        }
        resolved.append(entry)
        if line.quantity > available:
            shortfalls.append(
                {"sku": product.sku, "requested": line.quantity, "available": available}
            )

    # 1a. customer prices and deals, then free goods (only from stock the paid lines leave)
    quotes, free_goods = await deals.quote(
        db, tenant_id, branch_id, customer.id if customer else None,
        [(e["product"].id, e["quantity"], Decimal(str(e["price"].unit_price))) for e in resolved],
    )
    for e, q in zip(resolved, quotes):
        e.update(unit_price=q.unit_price, list_price=q.list_price, price_source=q.source,
                 promotion_id=q.promotion_id, free=False)
    free_notes: list[str] = []
    for f in free_goods:
        paid = next((e for e in resolved if e["product"].id == f.product_id), None)
        product = paid["product"] if paid else await db.get(Product, f.product_id)
        inv = paid["inv"] if paid else await db.scalar(
            select(Inventory).where(Inventory.tenant_id == tenant_id, Inventory.branch_id == branch_id,
                                    Inventory.product_id == f.product_id).with_for_update()
        )
        on_hand = inv.quantity_on_hand if inv else 0
        spare = on_hand - sum(e["quantity"] for e in resolved if e["product"].id == f.product_id)
        qty = max(min(f.quantity, spare), 0)
        if qty < f.quantity:
            free_notes.append(f"{f.promotion_name}: {qty} of {f.quantity} free {product.name_en} given (stock)")
        if qty > 0:
            resolved.append({"product": product, "price": None, "quantity": qty, "available": on_hand, "inv": inv,
                             "unit_price": Decimal("0.00"), "list_price": None, "price_source": "promotion",
                             "promotion_id": f.promotion_id, "free": True})

    # 1b. credit control for known customers
    credit_reasons: list[dict] = []
    if customer is not None:
        order_amount = sum(
            (e["unit_price"] * e["quantity"] for e in resolved), Decimal("0")
        )
        credit_reasons = await accounts.credit_check(db, tenant_id, customer, order_amount)

    order_number = await _generate_order_number(db, tenant_id)

    # 2a. any shortfall, credit problem or AI doubt -> hold for human review, create escalation, touch no stock
    if shortfalls or credit_reasons or review:
        order = Order(
            tenant_id=tenant_id,
            branch_id=branch_id,
            order_number=order_number,
            customer_id=getattr(data, "customer_id", None),
            customer_name=cust_name,
            customer_company=cust_company,
            whatsapp_number=cust_whatsapp,
            zone_id=cust_zone_id,
            status="requires_human_review",
            source=source,
            currency=resolved[0]["price"].currency,
            total_amount=Decimal("0"),
        )
        db.add(order)
        await db.flush()

        total = Decimal("0")
        for e in resolved:
            line_total = e["unit_price"] * e["quantity"]
            total += line_total
            db.add(_item(order, tenant_id, e, line_total))
        order.total_amount = total

        parts = []
        if credit_reasons:
            parts.append("Credit: " + "; ".join(r["message"] for r in credit_reasons))
        if shortfalls:
            rec = "; ".join(
                f"{s['sku']}: requested {s['requested']}, only {s['available']} available"
                for s in shortfalls
            )
            parts.append(f"Insufficient stock -> {rec}")
        if review:
            parts.append("Check the AI's order -> " + "; ".join(r["message"] for r in review))
        if credit_reasons:
            advice = "Approve to supply on credit anyway (partial where stock is short) or reject."
        elif shortfalls:
            advice = "Approve partial/backorder or reject."
        else:
            advice = "Correct the items if needed, then approve, or reject."
        reason_type = "credit" if credit_reasons else "insufficient_stock" if shortfalls else "ai_review"
        db.add(
            Escalation(
                tenant_id=tenant_id,
                branch_id=branch_id,
                reason_type=reason_type,
                context={"order_number": order_number, "shortfalls": shortfalls, "credit": credit_reasons,
                         "review": review, "lines": ai_lines or [], "free_notes": free_notes},
                ai_recommendation=f"{'. '.join(parts)}. {advice}",
                order_id=order.id,
                customer_name=cust_name,
                whatsapp_number=cust_whatsapp,
                status="open",
            )
        )
        await db.commit()
        await db.refresh(order)
        return order

    # 2b. all in stock -> confirm atomically
    order = Order(
        tenant_id=tenant_id,
        branch_id=branch_id,
        order_number=order_number,
        customer_id=getattr(data, "customer_id", None),
        customer_name=cust_name,
        customer_company=cust_company,
        whatsapp_number=cust_whatsapp,
        zone_id=cust_zone_id,
        status="confirmed",
        source=source,
        currency=resolved[0]["price"].currency,
        price_list_id=resolved[0]["price"].price_list_id,
        confirmed_at=now,
        total_amount=Decimal("0"),
    )
    db.add(order)
    await db.flush()

    total = Decimal("0")
    for e in resolved:
        line_total = e["unit_price"] * e["quantity"]
        total += line_total
        db.add(_item(order, tenant_id, e, line_total))
        # decrement stock via the immutable ledger (a product can be on a paid and a free line)
        before = e["inv"].quantity_on_hand
        after = before - e["quantity"]
        e["inv"].quantity_on_hand = after
        db.add(
            InventoryTransaction(
                tenant_id=tenant_id,
                branch_id=branch_id,
                product_id=e["product"].id,
                delta=-e["quantity"],
                quantity_before=before,
                quantity_after=after,
                reason="order",
                reference_type="order",
                reference_id=order.id,
                created_by=actor_id,
            )
        )

    order.total_amount = total
    slip_items = [
        {
            "sku": e["product"].sku,
            "name": e["product"].name_en + (" (FREE)" if e["free"] else ""),
            "quantity": e["quantity"],
            "unit_price": float(e["unit_price"]),
            "line_total": float(e["unit_price"] * e["quantity"]),
        }
        for e in resolved
    ]
    await printing_service.enqueue_for_order(db, tenant_id, order, slip_items)
    await db.commit()
    await db.refresh(order)

    # AI auto-assignment: if the order has a zone with a covering driver, assign
    # a driver and move to 'preparing' (warehouse still packs it before dispatch);
    # otherwise it stays 'confirmed' for the dispatcher.
    from app.modules.zones import service as zones_service
    await zones_service.auto_assign_order(db, tenant_id, order, actor_id=actor_id)
    await accounts.after_order_event(db, order, "confirmed", actor_id=actor_id)
    await erp.queue_safely(db, tenant_id, "order.confirmed", order.id)

    return order


async def list_orders(
    db: AsyncSession, tenant_id: uuid.UUID, scope: uuid.UUID | None = None
) -> list[Order]:
    q = select(Order).where(Order.tenant_id == tenant_id)
    if scope is not None:
        q = q.where(Order.branch_id == scope)
    return list(await db.scalars(q.order_by(Order.created_at.desc())))


async def get_order(
    db: AsyncSession, tenant_id: uuid.UUID, order_id: uuid.UUID, scope: uuid.UUID | None = None
) -> Order:
    order = await db.scalar(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
    )
    if not order or not in_scope(scope, order.branch_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


async def list_escalations(
    db: AsyncSession, tenant_id: uuid.UUID, *, open_only: bool = True, scope: uuid.UUID | None = None
) -> list[Escalation]:
    stmt = select(Escalation).where(Escalation.tenant_id == tenant_id)
    if scope is not None:
        stmt = stmt.where(Escalation.branch_id == scope)
    if open_only:
        stmt = stmt.where(Escalation.status == "open")
    return list(await db.scalars(stmt.order_by(Escalation.created_at.desc())))


async def resolve_escalation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    escalation_id: uuid.UUID,
    *,
    approve: bool,
    note: str | None = None,
    actor_id: uuid.UUID | None = None,
    scope: uuid.UUID | None = None,
) -> Escalation:
    """Human decision on a held order. Approve -> fulfil what stock allows and
    confirm; reject -> cancel the order. Either way the escalation is closed,
    and the customer is told on WhatsApp."""
    now = datetime.now(timezone.utc)

    esc = await db.scalar(
        select(Escalation).where(
            Escalation.id == escalation_id, Escalation.tenant_id == tenant_id
        )
    )
    if not esc or not in_scope(scope, esc.branch_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escalation not found")
    if esc.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "Escalation already resolved")

    order = None
    if esc.order_id:
        order = await db.scalar(select(Order).where(Order.id == esc.order_id))

    shorted: list[dict] = []
    if approve and order is not None:
        # fulfil each line up to available stock at the order's branch (partial fulfilment)
        for item in list(order.items):
            inv = await db.scalar(
                select(Inventory)
                .where(
                    Inventory.tenant_id == tenant_id,
                    Inventory.branch_id == order.branch_id,
                    Inventory.product_id == item.product_id,
                )
                .with_for_update()
            )
            available = inv.quantity_on_hand if inv else 0
            fulfil = min(item.quantity, available)
            if fulfil < item.quantity:
                shorted.append({"sku": item.sku, "name": item.product_name,
                                "requested": item.quantity, "supplied": max(fulfil, 0)})
            if fulfil <= 0:
                order.items.remove(item)  # none in stock: the line is dropped, not sent at full quantity
                continue
            before = available
            after = before - fulfil
            inv.quantity_on_hand = after
            item.quantity = fulfil
            item.line_total = Decimal(str(item.unit_price)) * fulfil
            db.add(
                InventoryTransaction(
                    tenant_id=tenant_id,
                    branch_id=order.branch_id,
                    product_id=item.product_id,
                    delta=-fulfil,
                    quantity_before=before,
                    quantity_after=after,
                    reason="order",
                    reference_type="order",
                    reference_id=order.id,
                    created_by=actor_id,
                )
            )
    if approve and order is not None and not order.items:
        # nothing at all could be supplied: approving means cancelling
        approve = False
        note = f"{note}. " if note else ""
        note += "Approved, but nothing was in stock, so the order was cancelled."
        order.status = "cancelled"
        order.cancelled_at = now
    elif approve and order is not None:
        order.total_amount = sum(
            (Decimal(str(i.line_total)) for i in order.items), Decimal("0")
        )
        order.status = "confirmed"
        order.confirmed_at = now
        slip_items = [
            {
                "sku": i.sku,
                "name": i.product_name,
                "quantity": i.quantity,
                "unit_price": float(i.unit_price),
                "line_total": float(i.line_total),
            }
            for i in order.items
        ]
        await printing_service.enqueue_for_order(db, tenant_id, order, slip_items)
        # auto-assign the now-confirmed order if possible
        from app.modules.zones import service as zones_service
        await db.flush()
        await zones_service.auto_assign_order(db, tenant_id, order, actor_id=actor_id)
    elif order is not None:
        order.status = "cancelled"
        order.cancelled_at = now

    esc.status = "resolved"
    esc.resolution = "approved" if approve else "rejected"
    esc.resolution_note = note
    esc.resolved_by = actor_id
    esc.resolved_at = now

    await db.commit()
    await db.refresh(esc)
    if order is not None:
        await notifications.queue_order_update(
            db, order, "approved" if approve else "rejected", {"shorted": shorted}
        )
        if approve:
            await accounts.after_order_event(db, order, "confirmed", actor_id=actor_id)
            await erp.queue_safely(db, tenant_id, "order.confirmed", order.id)
            await db.refresh(esc)
    return esc


# --- order lifecycle transitions -------------------------------------------

# who can move to what: current_status -> allowed next statuses
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "confirmed": {"preparing", "dispatched", "cancelled"},
    "preparing": {"dispatched", "cancelled"},
    "dispatched": {"delivered", "cancelled"},
    "delivered": {"completed"},
}

# timestamp column to stamp for a given target status (if the column exists)
_STATUS_TIMESTAMP = {
    "confirmed": "confirmed_at",
    "cancelled": "cancelled_at",
}


async def transition_order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    order_id: uuid.UUID,
    to_status: str,
    *,
    actor_id: uuid.UUID | None = None,
    actor_name: str | None = None,
    note: str | None = None,
    scope: uuid.UUID | None = None,
) -> Order:
    order = await db.scalar(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
    )
    if not order or not in_scope(scope, order.branch_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    current = order.status
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if to_status not in allowed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot move an order from '{current}' to '{to_status}'. "
            f"Allowed from here: {', '.join(sorted(allowed)) or 'none'}.",
        )

    now = datetime.now(timezone.utc)
    order.status = to_status
    ts_field = _STATUS_TIMESTAMP.get(to_status)
    if ts_field and hasattr(order, ts_field):
        setattr(order, ts_field, now)

    db.add(OrderEvent(
        tenant_id=tenant_id,
        order_id=order.id,
        from_status=current,
        to_status=to_status,
        actor_id=actor_id,
        actor_name=actor_name,
        note=note,
    ))
    await db.commit()
    await db.refresh(order)
    if to_status in notifications.STATUS_EVENTS:
        await notifications.queue_order_update(db, order, to_status)
    if to_status in ("delivered", "cancelled"):
        await accounts.after_order_event(db, order, to_status, actor_id=actor_id)
        await erp.queue_safely(db, tenant_id, f"order.{to_status}", order.id)
        await db.refresh(order)
    return order


async def list_order_events(
    db: AsyncSession, tenant_id: uuid.UUID, order_id: uuid.UUID
) -> list[OrderEvent]:
    return list(
        await db.scalars(
            select(OrderEvent)
            .where(OrderEvent.tenant_id == tenant_id, OrderEvent.order_id == order_id)
            .order_by(OrderEvent.created_at)
        )
    )