"""Zones + driver assignment.

- zones: create/list delivery areas
- driver<->zone links: which drivers cover which zones
- suggestion: for an order's zone, propose the covering driver with the fewest
  active (confirmed/dispatched) deliveries -- simple load balancing
- assignment: set an order's zone + driver
"""
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.order import Order
from app.db.models.order_event import OrderEvent
from app.db.models.user import User
from app.db.models.zone import DriverZone, Zone

_ACTIVE_STATUSES = ("confirmed", "dispatched")


# --- zones ---
async def create_zone(db: AsyncSession, tenant_id: uuid.UUID, name: str, description: str | None) -> Zone:
    exists = await db.scalar(
        select(Zone).where(Zone.tenant_id == tenant_id, Zone.name == name)
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Zone '{name}' already exists")
    zone = Zone(tenant_id=tenant_id, name=name, description=description)
    db.add(zone)
    await db.commit()
    await db.refresh(zone)
    return zone


async def list_zones(db: AsyncSession, tenant_id: uuid.UUID) -> list[Zone]:
    return list(await db.scalars(
        select(Zone).where(Zone.tenant_id == tenant_id).order_by(Zone.name)
    ))


async def delete_zone(db: AsyncSession, tenant_id: uuid.UUID, zone_id: uuid.UUID) -> None:
    zone = await db.scalar(select(Zone).where(Zone.id == zone_id, Zone.tenant_id == tenant_id))
    if not zone:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zone not found")
    await db.delete(zone)
    await db.commit()


# --- driver <-> zone links ---
async def set_driver_zones(
    db: AsyncSession, tenant_id: uuid.UUID, driver_id: uuid.UUID, zone_ids: list[uuid.UUID]
) -> None:
    driver = await db.scalar(
        select(User).where(User.id == driver_id, User.tenant_id == tenant_id)
    )
    if not driver:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver not found")
    # clear existing
    existing = list(await db.scalars(select(DriverZone).where(DriverZone.driver_id == driver_id)))
    for dz in existing:
        await db.delete(dz)
    # add new
    for zid in zone_ids:
        db.add(DriverZone(tenant_id=tenant_id, driver_id=driver_id, zone_id=zid))
    await db.commit()


async def list_driver_zones(db: AsyncSession, tenant_id: uuid.UUID, driver_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await db.scalars(select(DriverZone.zone_id).where(DriverZone.driver_id == driver_id))
    return list(rows)


async def drivers_for_zone(db: AsyncSession, tenant_id: uuid.UUID, zone_id: uuid.UUID) -> list[User]:
    rows = await db.scalars(
        select(User)
        .join(DriverZone, DriverZone.driver_id == User.id)
        .where(DriverZone.zone_id == zone_id, User.tenant_id == tenant_id, User.is_active.is_(True))
    )
    return list(rows)


async def _active_load(db: AsyncSession, tenant_id: uuid.UUID, driver_id: uuid.UUID) -> int:
    return await db.scalar(
        select(func.count(Order.id)).where(
            Order.tenant_id == tenant_id,
            Order.assigned_driver_id == driver_id,
            Order.status.in_(_ACTIVE_STATUSES),
        )
    ) or 0


async def suggest_driver(
    db: AsyncSession, tenant_id: uuid.UUID, zone_id: uuid.UUID
) -> User | None:
    """Covering driver with the fewest active deliveries."""
    drivers = await drivers_for_zone(db, tenant_id, zone_id)
    if not drivers:
        return None
    scored = [(await _active_load(db, tenant_id, d.id), d) for d in drivers]
    scored.sort(key=lambda x: x[0])
    return scored[0][1]


# --- order assignment ---
async def assign_order(
    db: AsyncSession, tenant_id: uuid.UUID, order_id: uuid.UUID,
    zone_id: uuid.UUID | None, driver_id: uuid.UUID | None,
) -> Order:
    order = await db.scalar(
        select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id)
    )
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if zone_id is not None:
        zone = await db.scalar(select(Zone).where(Zone.id == zone_id, Zone.tenant_id == tenant_id))
        if not zone:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Zone not found")
        order.zone_id = zone_id
    if driver_id is not None:
        driver = await db.scalar(
            select(User).where(User.id == driver_id, User.tenant_id == tenant_id)
        )
        if not driver:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver not found")
        order.assigned_driver_id = driver_id
    await db.commit()
    await db.refresh(order)
    return order


async def list_driver_orders(
    db: AsyncSession, tenant_id: uuid.UUID, driver_id: uuid.UUID
) -> list[Order]:
    return list(await db.scalars(
        select(Order)
        .where(
            Order.tenant_id == tenant_id,
            Order.assigned_driver_id == driver_id,
            Order.status.in_(("dispatched", "delivered")),
        )
        .order_by(Order.created_at.desc())
    ))


async def auto_assign_order(
    db: AsyncSession, tenant_id: uuid.UUID, order: Order, *, actor_id: uuid.UUID | None = None
) -> User | None:
    """AI auto-assignment: if a confirmed order has a zone and a covering driver
    exists, assign the best driver (fewest active deliveries) and dispatch it
    automatically. Returns the driver, or None if it should fall to the
    dispatcher queue (no zone, or no driver covers the zone)."""
    if order.status != "confirmed" or not order.zone_id:
        return None
    driver = await suggest_driver(db, tenant_id, order.zone_id)
    if not driver:
        return None
    order.assigned_driver_id = driver.id
    order.status = "dispatched"
    db.add(OrderEvent(
        tenant_id=tenant_id,
        order_id=order.id,
        from_status="confirmed",
        to_status="dispatched",
        actor_id=actor_id,
        actor_name="Auto-assign (AI)",
        note=f"Auto-assigned to {driver.full_name or driver.email}",
    ))
    await db.commit()
    await db.refresh(order)
    return driver