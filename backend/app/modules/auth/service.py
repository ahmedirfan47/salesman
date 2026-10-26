import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.branches import default_branch
from app.core.enums import UserRole
from app.core.security import hash_password, verify_password
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.schemas.auth import RegisterRequest


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return base or "tenant"


async def register_tenant(db: AsyncSession, data: RegisterRequest) -> tuple[Tenant, User]:
    """Create a new tenant plus its first OWNER user, atomically."""
    email = data.email.lower()

    if await db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    slug = _slugify(data.tenant_name)
    if await db.scalar(select(Tenant).where(Tenant.slug == slug)):
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    tenant = Tenant(name=data.tenant_name, slug=slug)
    db.add(tenant)
    await db.flush()  # populate tenant.id before creating the user
    await default_branch(db, tenant.id)  # every business starts with one branch

    user = User(
        tenant_id=tenant.id,
        email=email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role=UserRole.OWNER.value,
    )
    db.add(user)
    await db.commit()
    await db.refresh(tenant)
    await db.refresh(user)
    return tenant, user


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email.lower()))
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is inactive")
    return user