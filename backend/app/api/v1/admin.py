"""Stonic Console sign-in and admin accounts.

/platform/auth/login is the only console route open without a session.
"""
import uuid

from fastapi import APIRouter, Request

from app.core.deps import DBSession
from app.modules.platform import admins
from app.modules.platform.admins import CurrentAdmin
from app.schemas.console import AdminCreateIn, AdminLoginIn, AdminOut, AdminPasswordIn, AdminUpdateIn

router = APIRouter(prefix="/platform", tags=["console"])


@router.post("/auth/login")
async def login(data: AdminLoginIn, db: DBSession, request: Request) -> dict:
    admin, token = await admins.authenticate(db, data.email, data.password, request)
    return {"access_token": token, "token_type": "bearer", "admin": AdminOut.model_validate(admin)}


@router.get("/auth/me", response_model=AdminOut)
async def me(admin: CurrentAdmin) -> AdminOut:
    return AdminOut.model_validate(admin)


@router.get("/admins", response_model=list[AdminOut])
async def list_admins(db: DBSession, admin: CurrentAdmin) -> list[AdminOut]:
    return [AdminOut.model_validate(a) for a in await admins.list_admins(db)]


@router.post("/admins", response_model=AdminOut, status_code=201)
async def create_admin(data: AdminCreateIn, db: DBSession, admin: CurrentAdmin) -> AdminOut:
    return AdminOut.model_validate(
        await admins.create(db, admin, email=data.email, password=data.password, full_name=data.full_name)
    )


@router.patch("/admins/{admin_id}", response_model=AdminOut)
async def update_admin(admin_id: uuid.UUID, data: AdminUpdateIn, db: DBSession, admin: CurrentAdmin) -> AdminOut:
    return AdminOut.model_validate(
        await admins.update(db, admin, admin_id, is_active=data.is_active, full_name=data.full_name)
    )


@router.post("/admins/{admin_id}/password")
async def set_admin_password(admin_id: uuid.UUID, data: AdminPasswordIn, db: DBSession, admin: CurrentAdmin) -> dict:
    """Your own password needs the current one and returns a fresh session token; anyone else's ends their sessions."""
    target, token = await admins.set_password(db, admin, admin_id, data.password, data.current_password)
    return {"admin": AdminOut.model_validate(target), "access_token": token}