import uuid

import jwt
from fastapi import APIRouter, HTTPException, Request, status

from app.core.deps import CurrentUser, DBSession
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.db.models.user import User
from app.modules.auth import service
from app.modules.platform import access
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import MeOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, user.tenant_id, user.role, user.token_version),
        refresh_token=create_refresh_token(user.id, user.tenant_id, user.role, user.token_version),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: DBSession) -> TokenResponse:
    _, user = await service.register_tenant(db, data)
    return _tokens(user)


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: DBSession, request: Request) -> TokenResponse:
    user = await service.authenticate(db, data.email, data.password, request)
    return _tokens(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: DBSession) -> TokenResponse:
    try:
        payload = decode_token(data.refresh_token)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")

    user = await db.get(User, uuid.UUID(payload["sub"]))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    if payload.get("ver", 0) != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, access.SESSION_ENDED)
    problem = await access.blocked(db, user)
    if problem is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, problem[1])
    return _tokens(user)


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser, db: DBSession) -> MeOut:
    from app.core.branches import sees_all_branches
    from app.core.permissions import Capability, capabilities_for, has_capability
    from app.db.models.branch import Branch
    from app.modules.billing import service as billing

    data = MeOut.model_validate(user)
    data.capabilities = sorted(c.value for c in capabilities_for(user.role))
    data.sees_all_branches = sees_all_branches(user)
    if user.branch_id:
        branch = await db.get(Branch, user.branch_id)
        data.branch_name = branch.name if branch else None
    acct = await billing.account_state(db, user.tenant_id)
    data.billing_state = acct["state"]
    data.billing_message = billing.state_message(
        acct, admin=has_capability(user.role, Capability.VIEW_BILLING) and user.role != "demo"
    )
    data.is_platform_admin = billing.is_platform_admin(user)
    return data