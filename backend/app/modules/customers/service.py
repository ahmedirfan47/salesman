import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.customer import Customer


async def list_customers(db: AsyncSession, tenant_id: uuid.UUID) -> list[Customer]:
    return list(await db.scalars(
        select(Customer).where(Customer.tenant_id == tenant_id).order_by(Customer.name)
    ))


async def get_customer(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> Customer:
    c = await db.scalar(
        select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
    )
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return c


async def find_by_whatsapp(db: AsyncSession, tenant_id: uuid.UUID, number: str) -> Customer | None:
    return await db.scalar(
        select(Customer).where(
            Customer.tenant_id == tenant_id, Customer.whatsapp_number == number
        )
    )


async def create_customer(
    db: AsyncSession, tenant_id: uuid.UUID, *, name: str, company: str | None,
    whatsapp_number: str | None, address: str | None, zone_id: uuid.UUID | None,
) -> Customer:
    if whatsapp_number:
        dup = await find_by_whatsapp(db, tenant_id, whatsapp_number)
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, "A customer with that WhatsApp number already exists")
    c = Customer(
        tenant_id=tenant_id, name=name, company=company,
        whatsapp_number=whatsapp_number, address=address, zone_id=zone_id,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def update_customer(
    db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID, **fields
) -> Customer:
    c = await get_customer(db, tenant_id, customer_id)
    for k, v in fields.items():
        if v is not None:
            setattr(c, k, v)
    await db.commit()
    await db.refresh(c)
    return c