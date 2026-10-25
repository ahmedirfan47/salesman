"""User management within a tenant (admin capability)."""
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.core.security import hash_password
from app.db.models.user import User


def _valid_role(role: str) -> str:
    try:
        value = UserRole(role).value
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid role '{role}'")
    if value == UserRole.DEMO.value:
        # Demo accounts are created only by `python -m app.scripts.seed_demo`.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The demo role can't be assigned here")
    return value


async def list_users(db: AsyncSession, tenant_id: uuid.UUID) -> list[User]:
    return list(
        await db.scalars(
            select(User).where(User.tenant_id == tenant_id).order_by(User.created_at)
        )
    )


async def create_user(
    db: AsyncSession, tenant_id: uuid.UUID, *, email: str, password: str,
    full_name: str | None, role: str,
) -> User:
    role = _valid_role(role)
    if len(password) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Password must be at least 8 characters")
    exists = await db.scalar(select(User).where(User.email == email))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with that email already exists")
    user = User(
        tenant_id=tenant_id,
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, *,
    role: str | None = None, is_active: bool | None = None,
    acting_user_id: uuid.UUID | None = None,
) -> User:
    user = await db.scalar(
        select(User).where(User.id == user_id, User.tenant_id == tenant_id)
    )
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    # don't let an admin lock themselves out
    if acting_user_id and user.id == acting_user_id and is_active is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate your own account")
    if role is not None:
        if user.role == UserRole.OWNER.value:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The owner's role cannot be changed")
        user.role = _valid_role(role)
    if is_active is not None:
        user.is_active = is_active
    await db.commit()
    await db.refresh(user)
    return user