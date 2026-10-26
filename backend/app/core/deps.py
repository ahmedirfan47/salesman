import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ROLE_HIERARCHY, UserRole
from app.core.permissions import Capability, has_capability
from app.core.security import decode_token
from app.db.models.user import User
from app.db.session import get_session

_bearer = HTTPBearer(auto_error=True)

DBSession = Annotated[AsyncSession, Depends(get_session)]


_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
DEMO_READ_ONLY_MESSAGE = "This is a read-only demo account. Changes are disabled."


async def get_current_user(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    db: DBSession,
) -> User:
    try:
        payload = decode_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")

    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    # One choke point for the demo account: every authenticated route depends
    # on this function, so no write can slip through a route-level check.
    if user.role == UserRole.DEMO.value and request.method not in _SAFE_METHODS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, DEMO_READ_ONLY_MESSAGE)
    # Same choke point for accounts with an invoice overdue past the grace
    # period: everything stays viewable, nothing can be changed. Stonic's
    # own admins are exempt so they can still mark the invoice paid.
    if request.method not in _SAFE_METHODS:
        from app.modules.billing import service as billing

        if not billing.is_platform_admin(user) and await billing.is_read_only(db, user.tenant_id):
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, billing.READ_ONLY_DETAIL)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(minimum: UserRole):
    """Dependency factory enforcing a minimum role level."""

    async def _checker(user: CurrentUser) -> User:
        if ROLE_HIERARCHY[UserRole(user.role)] < ROLE_HIERARCHY[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return _checker


def require_capability(cap: Capability):
    """Dependency factory enforcing that the user's role has a capability."""

    async def _checker(user: CurrentUser) -> User:
        if not has_capability(user.role, cap):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Your role ('{user.role}') cannot perform this action.",
            )
        return user

    return _checker