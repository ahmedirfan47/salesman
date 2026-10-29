import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.branches import default_branch
from app.core.enums import UserRole
from app.core.security import hash_password, verify_password
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.modules.platform import access, activity, site
from app.schemas.auth import RegisterRequest


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return base or "tenant"


async def register_tenant(db: AsyncSession, data: RegisterRequest) -> tuple[Tenant, User]:
    """Create a new tenant plus its first OWNER user, atomically."""
    if not (await site.public(db))["sign_up_enabled"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, site.SIGN_UP_CLOSED)
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
        last_login_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.commit()
    await db.refresh(tenant)
    await db.refresh(user)
    return tenant, user


async def authenticate(db: AsyncSession, email: str, password: str, request: Request | None = None) -> User:
    """Check the password and whether this person may sign in now. Every attempt is recorded."""
    user = await db.scalar(select(User).where(User.email == email.lower()))
    if not user or not verify_password(password, user.password_hash):
        activity.login_event(db, request, email, user=user, success=False,
                             reason="wrong_password" if user else "unknown_email")
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    problem = await access.blocked(db, user)
    if problem is not None:
        reason, message = problem
        activity.login_event(db, request, email, user=user, success=False, reason=reason)
        await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, message)
    user.last_login_at = datetime.now(timezone.utc)
    activity.login_event(db, request, email, user=user, success=True, reason="ok")
    await db.commit()
    await db.refresh(user)
    return user