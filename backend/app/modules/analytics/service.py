"""Operational analytics: margins, customer drift, stuck orders.

Design notes:
- All figures come from real SQL aggregates -- nothing is estimated or
  inferred by a model. These functions are what an AI layer would *call*,
  never something it would answer from memory.
- Every query is tenant-scoped, consistent with the rest of the app.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.customer import Customer
from app.db.models.order import Order
from app.db.models.order_event import OrderEvent
from app.db.models.order_item import OrderItem

# Statuses that represent revenue actually earned (not cancelled/held).
REVENUE_STATUSES = ("confirmed", "preparing", "dispatched", "delivered", "completed")

# How long an order may sit in a status before it's considered stuck.
# Tuned per-status: 'preparing' should be quick; 'dispatched' can legitimately
# take most of a day on a delivery route.
STUCK_THRESHOLDS_HOURS: dict[str, int] = {
    "confirmed": 4,
    "preparing": 8,
    "dispatched": 24,
    "delivered": 48,
}


# --- margin analytics ------------------------------------------------------

@dataclass
class ProductMargin:
    sku: str
    name: str
    units_sold: int
    revenue: Decimal
    cost: Decimal
    profit: Decimal
    margin_percent: float | None
    """None when cost data is missing -- surfaced honestly rather than as 0."""


async def product_margins(
    db: AsyncSession, tenant_id: uuid.UUID, *, days: int = 30
) -> list[ProductMargin]:
    """Revenue, cost, and profit per product over a trailing window.

    Uses the `unit_cost` snapshotted onto each order item at order time, so
    historical margins stay accurate even if a product's cost changes later.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    rows = await db.execute(
        select(
            OrderItem.sku,
            OrderItem.product_name,
            func.sum(OrderItem.quantity).label("units"),
            func.sum(OrderItem.line_total).label("revenue"),
            func.sum(OrderItem.unit_cost * OrderItem.quantity).label("cost"),
            func.count(OrderItem.unit_cost).label("lines_with_cost"),
            func.count(OrderItem.id).label("total_lines"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            OrderItem.tenant_id == tenant_id,
            Order.status.in_(REVENUE_STATUSES),
            Order.created_at >= since,
        )
        .group_by(OrderItem.sku, OrderItem.product_name)
        .order_by(func.sum(OrderItem.line_total).desc())
    )

    out: list[ProductMargin] = []
    for r in rows:
        revenue = Decimal(str(r.revenue or 0))
        # If ANY line lacked cost data the margin would be overstated, so we
        # report it as unknown rather than as a misleadingly high number.
        has_full_cost = r.total_lines > 0 and r.lines_with_cost == r.total_lines
        cost = Decimal(str(r.cost or 0))
        profit = revenue - cost
        margin = float(profit / revenue * 100) if has_full_cost and revenue > 0 else None
        out.append(
            ProductMargin(
                sku=r.sku,
                name=r.product_name,
                units_sold=int(r.units or 0),
                revenue=revenue,
                cost=cost,
                profit=profit,
                margin_percent=round(margin, 1) if margin is not None else None,
            )
        )
    return out


# --- customer drift --------------------------------------------------------

@dataclass
class DriftingCustomer:
    customer_id: uuid.UUID
    name: str
    last_order_at: datetime | None
    days_since_last_order: int
    typical_gap_days: float | None
    order_count: int


async def drifting_customers(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    min_orders: int = 3,
    multiplier: float = 2.0,
) -> list[DriftingCustomer]:
    """Customers who have gone quiet relative to their OWN ordering rhythm.

    A fixed "30 days without an order" threshold is wrong for this business:
    a customer who orders weekly is in trouble at 3 weeks, while one who
    orders quarterly is fine. So we compare days-since-last-order against
    that customer's own average gap between orders.

    `min_orders` avoids flagging customers with too little history to have a
    meaningful pattern.
    """
    now = datetime.now(timezone.utc)

    rows = await db.execute(
        select(
            Customer.id,
            Customer.name,
            func.count(Order.id).label("order_count"),
            func.min(Order.created_at).label("first_order"),
            func.max(Order.created_at).label("last_order"),
        )
        .join(Order, Order.customer_id == Customer.id)
        .where(
            Customer.tenant_id == tenant_id,
            Customer.is_active.is_(True),
            Order.status.in_(REVENUE_STATUSES),
        )
        .group_by(Customer.id, Customer.name)
        .having(func.count(Order.id) >= min_orders)
    )

    out: list[DriftingCustomer] = []
    for r in rows:
        last = r.last_order
        first = r.first_order
        if last is None or first is None:
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)

        days_since = (now - last).days
        span_days = (last - first).days
        # gaps between N orders = N-1 intervals
        typical_gap = span_days / (r.order_count - 1) if r.order_count > 1 and span_days > 0 else None

        if typical_gap and days_since > typical_gap * multiplier:
            out.append(
                DriftingCustomer(
                    customer_id=r.id,
                    name=r.name,
                    last_order_at=last,
                    days_since_last_order=days_since,
                    typical_gap_days=round(typical_gap, 1),
                    order_count=int(r.order_count),
                )
            )

    out.sort(key=lambda c: c.days_since_last_order, reverse=True)
    return out


# --- stuck orders ----------------------------------------------------------

@dataclass
class StuckOrder:
    order_id: uuid.UUID
    order_number: str
    status: str
    customer_name: str | None
    hours_in_status: float
    threshold_hours: int


async def stuck_orders(db: AsyncSession, tenant_id: uuid.UUID) -> list[StuckOrder]:
    """Orders sitting in one status longer than that status allows.

    Uses the latest OrderEvent timestamp as "when it entered this status",
    falling back to the order's created_at if it has never transitioned.
    """
    now = datetime.now(timezone.utc)

    # latest event time per order
    latest_event = (
        select(
            OrderEvent.order_id.label("order_id"),
            func.max(OrderEvent.created_at).label("entered_at"),
        )
        .where(OrderEvent.tenant_id == tenant_id)
        .group_by(OrderEvent.order_id)
        .subquery()
    )

    rows = await db.execute(
        select(
            Order.id,
            Order.order_number,
            Order.status,
            Order.customer_name,
            Order.created_at,
            latest_event.c.entered_at,
        )
        .outerjoin(latest_event, latest_event.c.order_id == Order.id)
        .where(
            Order.tenant_id == tenant_id,
            Order.status.in_(tuple(STUCK_THRESHOLDS_HOURS.keys())),
        )
    )

    out: list[StuckOrder] = []
    for r in rows:
        entered = r.entered_at or r.created_at
        if entered is None:
            continue
        if entered.tzinfo is None:
            entered = entered.replace(tzinfo=timezone.utc)

        hours = (now - entered).total_seconds() / 3600
        threshold = STUCK_THRESHOLDS_HOURS[r.status]
        if hours > threshold:
            out.append(
                StuckOrder(
                    order_id=r.id,
                    order_number=r.order_number,
                    status=r.status,
                    customer_name=r.customer_name,
                    hours_in_status=round(hours, 1),
                    threshold_hours=threshold,
                )
            )

    out.sort(key=lambda o: o.hours_in_status, reverse=True)
    return out