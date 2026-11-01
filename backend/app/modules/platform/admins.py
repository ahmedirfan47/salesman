"""Stonic admin accounts: signing in to the Stonic Console and managing who has access.

Admins are not users of any business. Their tokens have type "admin", which the
business API refuses, and business tokens are refused here. The site switches
never affect admins.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import DBSession
from app.core.security import create_admin_token, decode_token, hash_password, verify_password
from app.db.models.platform import AdminAuditLog, PlatformAdmin
from app.modules.platform import site
from app.modules.platform.activity import audit, ip_of

SEEN_EVERY = timedelta(minutes=5)
SIGN_IN_REQUIRED = "Sign in to the Stonic Console."
_bearer = HTTPBearer(auto_error=False)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- signing in -------------------------------------------------------------------------------

async def authenticate(db: AsyncSession, email: str, password: str, request: Request | None = None) -> tuple[PlatformAdmin, str]:
    """Check an admin's password. Returns the admin and a console token. Every attempt is logged."""
    email = email.strip().lower()
    admin = await db.scalar(select(PlatformAdmin).where(PlatformAdmin.email == email))
    if admin is None:
        reason = "unknown email"
    elif not verify_password(password, admin.password_hash):
        reason = "wrong password"
    elif not admin.is_active:
        reason = "switched off"
    else:
        reason = None
    if reason:
        db.add(AdminAuditLog(actor_id=admin.id if admin else None, actor_email=email[:255], action="admin.sign_in_failed",
                             target_type="admin", target_label=email[:255], detail={"reason": reason, "ip": ip_of(request)}))
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    admin.last_login_at = admin.last_seen_at = _now()
    audit(db, admin, "admin.sign_in", target_type="admin", target_id=admin.id, target_label=admin.email,
          detail={"ip": ip_of(request)})
    await db.commit()
    await db.refresh(admin)
    return admin, create_admin_token(admin.id, admin.token_version)


async def get_current_admin(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)], db: DBSession,
) -> PlatformAdmin:
    """The signed-in Stonic admin. Business tokens and expired sessions get 401."""
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, SIGN_IN_REQUIRED)
    try:
        payload = decode_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your console session has expired. Sign in again.")
    if payload.get("type") != "admin":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, SIGN_IN_REQUIRED)
    admin = await db.get(PlatformAdmin, uuid.UUID(payload["sub"]))
    if admin is None or not admin.is_active or payload.get("ver", 0) != admin.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your console session has ended. Sign in again.")
    if admin.last_seen_at is None or _now() - admin.last_seen_at > SEEN_EVERY:
        admin.last_seen_at = _now()
        await db.commit()
    return admin


CurrentAdmin = Annotated[PlatformAdmin, Depends(get_current_admin)]


# ---- managing admins --------------------------------------------------------------------------

def _check_password(password: str) -> None:
    if len(password) < 10:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Admin passwords need at least 10 characters")


async def list_admins(db: AsyncSession) -> list[PlatformAdmin]:
    return list(await db.scalars(select(PlatformAdmin).order_by(PlatformAdmin.created_at)))


async def _get(db: AsyncSession, admin_id: uuid.UUID) -> PlatformAdmin:
    a = await db.get(PlatformAdmin, admin_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Admin not found")
    return a


async def create(db: AsyncSession, actor: PlatformAdmin | None, *, email: str, password: str,
                 full_name: str | None) -> PlatformAdmin:
    """Add an admin. `actor` is None only for the first admin, made from the command line."""
    email = email.strip().lower()
    _check_password(password)
    if await db.scalar(select(PlatformAdmin.id).where(PlatformAdmin.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "There is already an admin with that email")
    a = PlatformAdmin(email=email, password_hash=hash_password(password), full_name=(full_name or "").strip() or None)
    db.add(a)
    await db.flush()
    if actor is not None:
        audit(db, actor, "admin.create", target_type="admin", target_id=a.id, target_label=a.email)
    site.invalidate()
    await db.commit()
    await db.refresh(a)
    return a


async def update(db: AsyncSession, actor: PlatformAdmin, admin_id: uuid.UUID, *, is_active: bool | None,
                 full_name: str | None) -> PlatformAdmin:
    a = await _get(db, admin_id)
    changes: dict = {}
    if is_active is not None and is_active != a.is_active:
        if not is_active and a.id == actor.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "You can't switch off your own admin account")
        a.is_active = is_active
        if not is_active:
            a.token_version += 1
        changes["is_active"] = is_active
    if full_name is not None and (full_name.strip() or None) != a.full_name:
        changes["full_name"] = {"from": a.full_name, "to": full_name.strip() or None}
        a.full_name = full_name.strip() or None
    if changes:
        audit(db, actor, "admin.update", target_type="admin", target_id=a.id, target_label=a.email, detail=changes)
        site.invalidate()
        await db.commit()
        await db.refresh(a)
    return a


async def set_password(db: AsyncSession, actor: PlatformAdmin, admin_id: uuid.UUID, password: str,
                       current_password: str | None = None) -> tuple[PlatformAdmin, str | None]:
    """Set an admin's password. Changing your own needs your current one and keeps you signed in."""
    a = await _get(db, admin_id)
    _check_password(password)
    own = a.id == actor.id
    if own and not (current_password and verify_password(current_password, a.password_hash)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Your current password is wrong")
    a.password_hash = hash_password(password)
    a.token_version += 1  # every other session with the old password ends
    audit(db, actor, "admin.password", target_type="admin", target_id=a.id, target_label=a.email)
    await db.commit()
    await db.refresh(a)
    return a, create_admin_token(a.id, a.token_version) if own else None


async def ensure_admin(db: AsyncSession, *, email: str, password: str, full_name: str | None) -> tuple[PlatformAdmin, bool]:
    """For the command line: create the admin, or reset its password and switch it on. Returns (admin, created)."""
    email = email.strip().lower()
    _check_password(password)
    a = await db.scalar(select(PlatformAdmin).where(PlatformAdmin.email == email))
    if a is None:
        return await create(db, None, email=email, password=password, full_name=full_name), True
    a.password_hash = hash_password(password)
    a.is_active = True
    a.token_version += 1
    if full_name:
        a.full_name = full_name.strip()
    db.add(AdminAuditLog(actor_id=a.id, actor_email=a.email, action="admin.password", target_type="admin",
                         target_id=str(a.id), target_label=a.email, detail={"via": "command line"}))
    site.invalidate()
    await db.commit()
    await db.refresh(a)
    return a, False