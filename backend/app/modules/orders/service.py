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
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.escalation import Escalation
from app.db.models.inventory import Inventory
from app.db.models.inventory_transaction import InventoryTransaction
from app.db.models.order import Order
from app.db.models.order_event import OrderEvent
from app.db.models.order_item import OrderItem
from app.db.models.product import Product
from app.db.models.product_price import ProductPrice
from app.modules.printing import service as printing_service
from app.schemas.order import OrderCreate


async def _generate_order_number(db: AsyncSession, tenant_id: uuid.UUID) -> str:
    count = await db.scalar(
        select(func.count(Order.id)).where(Order.tenant_id == tenant_id)
    )
    return f"ORD-{(count or 0) + 1:05d}"


async def _current_price_row(
    db: AsyncSession, tenant_id: uuid.UUID, sku: str
) -> tuple[Product, ProductPrice] | None:
    row = await db.execute(
        select(Product, ProductPrice)
        .join(ProductPrice, ProductPrice.product_id == Product.id)
        .where(
            Product.tenant_id == tenant_id,
            Product.sku == sku,
            ProductPrice.effective_to.is_(None),
        )
    )
    return row.first()


async def create_order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: OrderCreate,
    *,
    actor_id: uuid.UUID | None = None,
) -> Order:
    now = datetime.now(timezone.utc)

    # 0. if the order is for a known customer, pull their details + zone so the
    #    order is ready for (auto-)assignment. Explicit fields on the request win.
    cust_zone_id = None
    cust_name = data.customer_name
    cust_company = data.customer_company
    cust_whatsapp = data.whatsapp_number
    if getattr(data, "customer_id", None):
        from app.db.models.customer import Customer
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

    # 1. resolve every line to product + current price, collecting shortfalls
    resolved: list[dict] = []
    shortfalls: list[dict] = []

    for line in data.items:
        found = await _current_price_row(db, tenant_id, line.sku)
        if not found:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"No active price for SKU '{line.sku}'. Cannot price this order.",
            )
        product, price = found

        # lock the inventory row for this product
        inv = await db.scalar(
            select(Inventory)
            .where(Inventory.tenant_id == tenant_id, Inventory.product_id == product.id)
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

    order_number = await _generate_order_number(db, tenant_id)

    # 2a. any shortfall -> hold for human review, create escalation, touch no stock
    if shortfalls:
        order = Order(
            tenant_id=tenant_id,
            order_number=order_number,
            customer_id=getattr(data, "customer_id", None),
            customer_name=cust_name,
            customer_company=cust_company,
            whatsapp_number=cust_whatsapp,
            zone_id=cust_zone_id,
            status="requires_human_review",
            currency=resolved[0]["price"].currency,
            total_amount=Decimal("0"),
        )
        db.add(order)
        await db.flush()

        total = Decimal("0")
        for e in resolved:
            line_total = Decimal(str(e["price"].unit_price)) * e["quantity"]
            total += line_total
            db.add(
                OrderItem(
                    order_id=order.id,
                    tenant_id=tenant_id,
                    product_id=e["product"].id,
                    sku=e["product"].sku,
                    product_name=e["product"].name_en,
                    quantity=e["quantity"],
                    unit_price=e["price"].unit_price,
                    line_total=line_total,
                    available_at_order=e["available"],
                )
            )
        order.total_amount = total

        rec = "; ".join(
            f"{s['sku']}: requested {s['requested']}, only {s['available']} available"
            for s in shortfalls
        )
        db.add(
            Escalation(
                tenant_id=tenant_id,
                reason_type="insufficient_stock",
                context={"order_number": order_number, "shortfalls": shortfalls},
                ai_recommendation=f"Insufficient stock -> {rec}. Approve partial/backorder or reject.",
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
        order_number=order_number,
        customer_id=getattr(data, "customer_id", None),
        customer_name=cust_name,
        customer_company=cust_company,
        whatsapp_number=cust_whatsapp,
        zone_id=cust_zone_id,
        status="confirmed",
        currency=resolved[0]["price"].currency,
        price_list_id=resolved[0]["price"].price_list_id,
        confirmed_at=now,
        total_amount=Decimal("0"),
    )
    db.add(order)
    await db.flush()

    total = Decimal("0")
    for e in resolved:
        line_total = Decimal(str(e["price"].unit_price)) * e["quantity"]
        total += line_total
        db.add(
            OrderItem(
                order_id=order.id,
                tenant_id=tenant_id,
                product_id=e["product"].id,
                sku=e["product"].sku,
                product_name=e["product"].name_en,
                quantity=e["quantity"],
                unit_price=e["price"].unit_price,
                line_total=line_total,
                available_at_order=e["available"],
            )
        )
        # decrement stock via the immutable ledger
        before = e["available"]
        after = before - e["quantity"]
        e["inv"].quantity_on_hand = after
        db.add(
            InventoryTransaction(
                tenant_id=tenant_id,
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
            "name": e["product"].name_en,
            "quantity": e["quantity"],
            "unit_price": float(e["price"].unit_price),
            "line_total": float(Decimal(str(e["price"].unit_price)) * e["quantity"]),
        }
        for e in resolved
    ]
    await printing_service.enqueue_for_order(db, tenant_id, order, slip_items)
    await db.commit()
    await db.refresh(order)

    # AI auto-assignment: if the order has a zone with a covering driver, assign
    # + dispatch automatically; otherwise it stays 'confirmed' for the dispatcher.
    from app.modules.zones import service as zones_service
    await zones_service.auto_assign_order(db, tenant_id, order, actor_id=actor_id)

    return order


async def list_orders(db: AsyncSession, tenant_id: uuid.UUID) -> list[Order]:
    return list(
        await db.scalars(
            select(Order).where(Order.tenant_id == tenant_id).order_by(Order.created_at.desc())
        )
    )


async def get_order(db: AsyncSession, tenant_id: uuid.UUID, order_id: uuid.UUID) -> Order:
    order = await db.scalar(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
    )
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


async def list_escalations(
    db: AsyncSession, tenant_id: uuid.UUID, *, open_only: bool = True
) -> list[Escalation]:
    stmt = select(Escalation).where(Escalation.tenant_id == tenant_id)
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
) -> Escalation:
    """Human decision on a held order. Approve -> fulfil what stock allows and
    confirm; reject -> cancel the order. Either way the escalation is closed."""
    now = datetime.now(timezone.utc)

    esc = await db.scalar(
        select(Escalation).where(
            Escalation.id == escalation_id, Escalation.tenant_id == tenant_id
        )
    )
    if not esc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escalation not found")
    if esc.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "Escalation already resolved")

    order = None
    if esc.order_id:
        order = await db.scalar(select(Order).where(Order.id == esc.order_id))

    if approve and order is not None:
        # fulfil each line up to available stock (partial fulfilment)
        for item in order.items:
            inv = await db.scalar(
                select(Inventory)
                .where(Inventory.tenant_id == tenant_id, Inventory.product_id == item.product_id)
                .with_for_update()
            )
            available = inv.quantity_on_hand if inv else 0
            fulfil = min(item.quantity, available)
            if fulfil <= 0:
                continue
            before = available
            after = before - fulfil
            inv.quantity_on_hand = after
            item.quantity = fulfil
            item.line_total = Decimal(str(item.unit_price)) * fulfil
            db.add(
                InventoryTransaction(
                    tenant_id=tenant_id,
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
    return esc


# --- order lifecycle transitions -------------------------------------------

# who can move to what: current_status -> allowed next statuses
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "confirmed": {"dispatched", "cancelled"},
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
) -> Order:
    order = await db.scalar(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
    )
    if not order:
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