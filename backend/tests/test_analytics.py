"""Tests for margin, drift, and stuck-order analytics."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models.customer import Customer
from app.db.models.order import Order
from app.db.models.order_event import OrderEvent
from app.db.models.order_item import OrderItem
from app.db.models.product import Product
from app.db.models.tenant import Tenant
from app.modules.analytics.service import (
    drifting_customers,
    product_margins,
    stuck_orders,
)

pytestmark = pytest.mark.asyncio


def _ago(**kw):
    return datetime.now(timezone.utc) - timedelta(**kw)


async def _tenant(db, name="Test Co"):
    # slug must be unique + not null on the real Tenant model -- derive one
    # from the name plus a short random suffix so multiple tenants created
    # within the same test (e.g. "Mine" / "Theirs") never collide.
    slug = f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}"
    t = Tenant(name=name, slug=slug)
    db.add(t)
    await db.flush()
    return t


async def _product(db, tenant_id, *, sku="APPLE", name="Apples"):
    """order_items.product_id is a real FK -- a product row must exist
    first. Reuses an existing row for the same tenant+sku (the unique
    constraint) instead of trying to insert a duplicate."""
    existing = await db.scalar(
        select(Product).where(Product.tenant_id == tenant_id, Product.sku == sku)
    )
    if existing:
        return existing
    p = Product(tenant_id=tenant_id, sku=sku, name_en=name)
    db.add(p)
    await db.flush()
    return p


async def _order(db, tenant_id, *, status="completed", created=None,
                 customer_id=None, customer_name=None, number="ORD-1"):
    o = Order(
        tenant_id=tenant_id, order_number=number, status=status,
        created_at=created or _ago(days=1),
        customer_id=customer_id, customer_name=customer_name,
    )
    db.add(o)
    await db.flush()
    return o


async def _item(db, tenant_id, order, *, sku="APPLE", name="Apples",
                qty=10, price=100, cost=60):
    product = await _product(db, tenant_id, sku=sku, name=name)
    it = OrderItem(
        tenant_id=tenant_id, order_id=order.id, product_id=product.id,
        sku=sku, product_name=name, quantity=qty,
        unit_price=price, line_total=price * qty, unit_cost=cost,
    )
    db.add(it)
    await db.flush()
    return it


# --- margins ---

async def test_margin_calculated_from_snapshotted_cost(db):
    t = await _tenant(db)
    o = await _order(db, t.id)
    await _item(db, t.id, o, qty=10, price=100, cost=60)
    await db.commit()

    rows = await product_margins(db, t.id)
    assert len(rows) == 1
    m = rows[0]
    assert m.units_sold == 10
    assert m.revenue == 1000
    assert m.cost == 600
    assert m.profit == 400
    assert m.margin_percent == 40.0


async def test_margin_is_none_when_cost_missing(db):
    """Missing cost must surface as unknown, never as a misleading 0% or 100%."""
    t = await _tenant(db)
    o = await _order(db, t.id)
    await _item(db, t.id, o, cost=None)
    await db.commit()

    rows = await product_margins(db, t.id)
    assert rows[0].margin_percent is None


async def test_margin_unknown_when_only_some_lines_have_cost(db):
    """Partial cost data would overstate margin -- must report unknown."""
    t = await _tenant(db)
    o = await _order(db, t.id)
    await _item(db, t.id, o, sku="A", name="A", qty=5, price=100, cost=60)
    await _item(db, t.id, o, sku="A", name="A", qty=5, price=100, cost=None)
    await db.commit()

    rows = await product_margins(db, t.id)
    assert rows[0].margin_percent is None


async def test_cancelled_orders_excluded_from_margins(db):
    t = await _tenant(db)
    ok = await _order(db, t.id, status="completed", number="ORD-1")
    await _item(db, t.id, ok, qty=5, price=100, cost=50)
    bad = await _order(db, t.id, status="cancelled", number="ORD-2")
    await _item(db, t.id, bad, qty=99, price=100, cost=50)
    await db.commit()

    rows = await product_margins(db, t.id)
    assert rows[0].units_sold == 5  # cancelled order's 99 units ignored


# --- customer drift ---

async def test_weekly_customer_flagged_after_long_gap(db):
    """A customer who ordered weekly and has been silent 30 days is drifting."""
    t = await _tenant(db)
    c = Customer(tenant_id=t.id, name="Souq Weekly")
    db.add(c)
    await db.flush()
    for i in range(5):
        await _order(db, t.id, customer_id=c.id,
                     created=_ago(days=30 + (4 - i) * 7), number=f"W-{i}")
    await db.commit()

    rows = await drifting_customers(db, t.id)
    assert len(rows) == 1
    assert rows[0].name == "Souq Weekly"
    assert rows[0].days_since_last_order >= 30


async def test_customer_ordering_on_schedule_not_flagged(db):
    t = await _tenant(db)
    c = Customer(tenant_id=t.id, name="Souq Regular")
    db.add(c)
    await db.flush()
    for i in range(5):
        await _order(db, t.id, customer_id=c.id,
                     created=_ago(days=(4 - i) * 7 + 2), number=f"R-{i}")
    await db.commit()

    assert await drifting_customers(db, t.id) == []


async def test_customer_with_too_little_history_not_flagged(db):
    """Two orders isn't a pattern -- don't cry wolf."""
    t = await _tenant(db)
    c = Customer(tenant_id=t.id, name="Newcomer")
    db.add(c)
    await db.flush()
    await _order(db, t.id, customer_id=c.id, created=_ago(days=200), number="N-1")
    await _order(db, t.id, customer_id=c.id, created=_ago(days=190), number="N-2")
    await db.commit()

    assert await drifting_customers(db, t.id) == []


# --- stuck orders ---

async def test_order_stuck_in_preparing_is_flagged(db):
    t = await _tenant(db)
    o = await _order(db, t.id, status="preparing", created=_ago(hours=20))
    db.add(OrderEvent(tenant_id=t.id, order_id=o.id, from_status="confirmed",
                      to_status="preparing", created_at=_ago(hours=20)))
    await db.commit()

    rows = await stuck_orders(db, t.id)
    assert len(rows) == 1
    assert rows[0].status == "preparing"
    assert rows[0].hours_in_status > 8


async def test_recently_dispatched_order_not_flagged(db):
    """Dispatched has a 24h threshold -- 3 hours out on a route is normal."""
    t = await _tenant(db)
    o = await _order(db, t.id, status="dispatched", created=_ago(hours=3))
    db.add(OrderEvent(tenant_id=t.id, order_id=o.id, from_status="preparing",
                      to_status="dispatched", created_at=_ago(hours=3)))
    await db.commit()

    assert await stuck_orders(db, t.id) == []


async def test_completed_orders_never_stuck(db):
    t = await _tenant(db)
    o = await _order(db, t.id, status="completed", created=_ago(days=60))
    db.add(OrderEvent(tenant_id=t.id, order_id=o.id, to_status="completed",
                      created_at=_ago(days=60)))
    await db.commit()

    assert await stuck_orders(db, t.id) == []


async def test_tenant_isolation_on_all_analytics(db):
    """Another tenant's data must never leak into these results."""
    mine = await _tenant(db, "Mine")
    theirs = await _tenant(db, "Theirs")

    o = await _order(db, theirs.id, status="preparing",
                     created=_ago(hours=99), number="X-1")
    await _item(db, theirs.id, o)
    db.add(OrderEvent(tenant_id=theirs.id, order_id=o.id,
                      to_status="preparing", created_at=_ago(hours=99)))
    await db.commit()

    assert await product_margins(db, mine.id) == []
    assert await stuck_orders(db, mine.id) == []