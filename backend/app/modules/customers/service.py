"""Customers. Each customer belongs to one branch, which serves and delivers to them."""
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.branches import get_branch, in_scope, resolve_branch
from app.db.models.customer import Customer
from app.db.models.zone import Zone


async def list_customers(db: AsyncSession, tenant_id: uuid.UUID, scope: uuid.UUID | None = None) -> list[Customer]:
    q = select(Customer).where(Customer.tenant_id == tenant_id)
    if scope is not None:
        q = q.where(Customer.branch_id == scope)
    return list(await db.scalars(q.order_by(Customer.name)))


async def get_customer(
    db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID, scope: uuid.UUID | None = None
) -> Customer:
    c = await db.scalar(
        select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
    )
    if not c or not in_scope(scope, c.branch_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return c


async def find_by_whatsapp(db: AsyncSession, tenant_id: uuid.UUID, number: str) -> Customer | None:
    return await db.scalar(
        select(Customer).where(
            Customer.tenant_id == tenant_id, Customer.whatsapp_number == number
        )
    )


async def _zone(db: AsyncSession, tenant_id: uuid.UUID, zone_id: uuid.UUID) -> Zone:
    zone = await db.scalar(select(Zone).where(Zone.id == zone_id, Zone.tenant_id == tenant_id))
    if not zone:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Zone not found")
    return zone


async def create_customer(
    db: AsyncSession, tenant_id: uuid.UUID, *, name: str, company: str | None,
    whatsapp_number: str | None, address: str | None, zone_id: uuid.UUID | None,
    branch_id: uuid.UUID | None = None, vat_number: str | None = None, scope: uuid.UUID | None = None,
) -> Customer:
    if whatsapp_number:
        dup = await find_by_whatsapp(db, tenant_id, whatsapp_number)
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, "A customer with that WhatsApp number already exists")
    zone = await _zone(db, tenant_id, zone_id) if zone_id else None
    # the zone decides the branch unless one is given explicitly
    branch = await resolve_branch(db, tenant_id, scope, branch_id or (zone.branch_id if zone else None))
    if zone and zone.branch_id != branch:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That zone belongs to another branch")
    c = Customer(
        tenant_id=tenant_id, branch_id=branch, name=name, company=company,
        whatsapp_number=whatsapp_number, address=address, zone_id=zone_id,
        vat_number=(vat_number or "").strip() or None,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def update_customer(
    db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID, *, scope: uuid.UUID | None = None, **fields
) -> Customer:
    c = await get_customer(db, tenant_id, customer_id, scope)
    if fields.get("branch_id") is not None:
        await get_branch(db, tenant_id, fields["branch_id"])
        if not in_scope(scope, fields["branch_id"]):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "That branch is outside your access")
        if fields["branch_id"] != c.branch_id and "zone_id" not in fields:
            fields["zone_id"] = None  # the old zone belongs to the old branch
    if "zone_id" in fields:
        zone_id = fields.pop("zone_id")
        if zone_id is not None:
            zone = await _zone(db, tenant_id, zone_id)
            if zone.branch_id != fields.get("branch_id", c.branch_id):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That zone belongs to another branch")
        c.zone_id = zone_id
    for k, v in fields.items():
        if v is not None:
            setattr(c, k, v)
    await db.commit()
    await db.refresh(c)
    return c