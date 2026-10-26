"""Branch management. The access token is write-only: it is never returned by the API."""
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.branches import default_branch, get_branch
from app.db.models.branch import Branch


def to_out(b: Branch) -> dict:
    return {
        "id": b.id, "name": b.name, "city": b.city, "address": b.address,
        "is_default": b.is_default, "is_active": b.is_active,
        "whatsapp_phone_number_id": b.whatsapp_phone_number_id,
        "whatsapp_display_number": b.whatsapp_display_number,
        "whatsapp_update_template": b.whatsapp_update_template,
        "whatsapp_connected": bool(b.whatsapp_phone_number_id and b.whatsapp_access_token),
        "order_updates_enabled": b.order_updates_enabled,
        "created_at": b.created_at,
    }


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


async def list_branches(db: AsyncSession, tenant_id: uuid.UUID, only: uuid.UUID | None = None) -> list[Branch]:
    await default_branch(db, tenant_id)  # make sure older tenants have one
    q = select(Branch).where(Branch.tenant_id == tenant_id)
    if only is not None:
        q = q.where(Branch.id == only)
    rows = list(await db.scalars(q.order_by(Branch.is_default.desc(), Branch.name)))
    await db.commit()
    return rows


async def _check_number(db: AsyncSession, number_id: str | None, branch_id: uuid.UUID | None) -> None:
    if not number_id:
        return
    other = await db.scalar(select(Branch).where(Branch.whatsapp_phone_number_id == number_id))
    if other is not None and other.id != branch_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "That WhatsApp number is already connected to another branch")


async def _check_name(db: AsyncSession, tenant_id: uuid.UUID, name: str, branch_id: uuid.UUID | None) -> None:
    other = await db.scalar(select(Branch).where(Branch.tenant_id == tenant_id, Branch.name == name))
    if other is not None and other.id != branch_id:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A branch called '{name}' already exists")


async def _make_default(db: AsyncSession, tenant_id: uuid.UUID, branch: Branch) -> None:
    await db.execute(
        update(Branch).where(Branch.tenant_id == tenant_id, Branch.id != branch.id).values(is_default=False)
    )
    branch.is_default = True
    branch.is_active = True


async def create_branch(db: AsyncSession, tenant_id: uuid.UUID, data: dict) -> Branch:
    await default_branch(db, tenant_id)
    name = data["name"].strip()
    await _check_name(db, tenant_id, name, None)
    number_id = _clean(data.get("whatsapp_phone_number_id"))
    await _check_number(db, number_id, None)
    branch = Branch(
        tenant_id=tenant_id, name=name, city=_clean(data.get("city")), address=_clean(data.get("address")),
        is_default=False, is_active=True,
        whatsapp_phone_number_id=number_id,
        whatsapp_access_token=_clean(data.get("whatsapp_access_token")),
        whatsapp_display_number=_clean(data.get("whatsapp_display_number")),
        whatsapp_update_template=_clean(data.get("whatsapp_update_template")),
        order_updates_enabled=data.get("order_updates_enabled", True),
    )
    db.add(branch)
    await db.flush()
    if data.get("is_default"):
        await _make_default(db, tenant_id, branch)
    await db.commit()
    await db.refresh(branch)
    return branch


async def update_branch(db: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID, data: dict) -> Branch:
    branch = await get_branch(db, tenant_id, branch_id)
    if "name" in data and data["name"]:
        name = data["name"].strip()
        await _check_name(db, tenant_id, name, branch.id)
        branch.name = name
    for field in ("city", "address", "whatsapp_display_number", "whatsapp_update_template"):
        if field in data:
            setattr(branch, field, _clean(data[field]))
    if "whatsapp_phone_number_id" in data:
        number_id = _clean(data["whatsapp_phone_number_id"])
        await _check_number(db, number_id, branch.id)
        branch.whatsapp_phone_number_id = number_id
    if "whatsapp_access_token" in data and data["whatsapp_access_token"] is not None:
        branch.whatsapp_access_token = _clean(data["whatsapp_access_token"])
    if data.get("order_updates_enabled") is not None:
        branch.order_updates_enabled = data["order_updates_enabled"]
    if data.get("is_default"):
        await _make_default(db, tenant_id, branch)
    if data.get("is_active") is False:
        if branch.is_default:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "The default branch can't be deactivated. Make another branch the default first.")
        branch.is_active = False
    elif data.get("is_active") is True:
        branch.is_active = True
    await db.commit()
    await db.refresh(branch)
    return branch