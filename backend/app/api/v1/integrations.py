"""Integrations: connect an ERP (Odoo first), map it, switch syncing on, and follow what was sent."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.core.deps import CurrentUser, DBSession, require_capability
from app.core.permissions import Capability
from app.db.models.branch import Branch
from app.modules.integrations import service
from app.schemas.integration import (
    BalanceOut, ConnectIn, ConnectionOut, ConnectOut, Counts, EventOut, OverviewOut, ProviderOut, SettingsIn,
)

router = APIRouter(
    prefix="/integrations", tags=["integrations"],
    dependencies=[Depends(require_capability(Capability.MANAGE_INTEGRATIONS))],
)


def _providers() -> list[ProviderOut]:
    return [ProviderOut(key=k, **v) for k, v in service.PROVIDERS.items()]


@router.get("", response_model=OverviewOut)
async def overview(db: DBSession, user: CurrentUser) -> OverviewOut:
    conn = await service.get_connection(db, user.tenant_id)
    if conn is None:
        return OverviewOut(providers=_providers(), connection=None)
    out = OverviewOut(
        providers=_providers(), connection=ConnectionOut.model_validate(conn),
        problems=await service.problems(db, conn), counts=Counts(**await service.counts(db, conn)),
    )
    await db.commit()
    return out


@router.post("/connect", response_model=ConnectOut)
async def connect(data: ConnectIn, db: DBSession, user: CurrentUser) -> ConnectOut:
    conn, options = await service.connect(
        db, user.tenant_id, provider=data.provider, url=data.url, database=data.database,
        username=data.username, api_key=data.api_key,
    )
    return ConnectOut(connection=ConnectionOut.model_validate(conn), options=options,
                      problems=await service.problems(db, conn, options))


@router.get("/options", response_model=ConnectOut)
async def options(db: DBSession, user: CurrentUser) -> ConnectOut:
    conn = await service.require_connection(db, user.tenant_id)
    found = await service.options(db, conn)
    return ConnectOut(connection=ConnectionOut.model_validate(conn), options=found,
                      problems=await service.problems(db, conn, found))


@router.put("/settings", response_model=ConnectionOut)
async def update_settings(data: SettingsIn, db: DBSession, user: CurrentUser) -> ConnectionOut:
    conn = await service.require_connection(db, user.tenant_id)
    payload = data.model_dump(exclude_unset=True)
    if "branches" in payload and payload["branches"] is not None:
        mine = {str(b) for b in await db.scalars(select(Branch.id).where(Branch.tenant_id == user.tenant_id))}
        payload["branches"] = {k: v for k, v in payload["branches"].items() if k in mine}
    conn = await service.update_settings(db, conn, payload)
    return ConnectionOut.model_validate(conn)


@router.post("/activate", response_model=ConnectionOut)
async def activate(db: DBSession, user: CurrentUser) -> ConnectionOut:
    conn = await service.require_connection(db, user.tenant_id)
    return ConnectionOut.model_validate(await service.activate(db, conn))


@router.post("/pause", response_model=ConnectionOut)
async def pause(db: DBSession, user: CurrentUser) -> ConnectionOut:
    conn = await service.require_connection(db, user.tenant_id)
    return ConnectionOut.model_validate(await service.pause(db, conn))


@router.delete("", status_code=204)
async def disconnect(db: DBSession, user: CurrentUser) -> None:
    conn = await service.require_connection(db, user.tenant_id)
    await service.disconnect(db, conn)


@router.post("/sync", status_code=202)
async def sync_now(db: DBSession, user: CurrentUser) -> dict:
    conn = await service.require_connection(db, user.tenant_id)
    await service.sync_now(db, conn)
    return {"queued": True}


@router.get("/events", response_model=list[EventOut])
async def events(
    db: DBSession, user: CurrentUser,
    status: Literal["attention", "ok", "warning", "failed", "skipped", "pending"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[EventOut]:
    conn = await service.require_connection(db, user.tenant_id)
    return [EventOut.model_validate(e) for e in await service.list_events(db, conn, status_=status, limit=limit)]


@router.post("/events/{event_id}/retry", response_model=EventOut)
async def retry(event_id: uuid.UUID, db: DBSession, user: CurrentUser) -> EventOut:
    conn = await service.require_connection(db, user.tenant_id)
    return EventOut.model_validate(await service.retry(db, conn, event_id))


@router.get("/balances", response_model=list[BalanceOut])
async def balances(db: DBSession, user: CurrentUser) -> list[BalanceOut]:
    conn = await service.require_connection(db, user.tenant_id)
    return [BalanceOut(**row) for row in await service.balances(db, conn)]