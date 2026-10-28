"""Links (which ERP record a Salesman record became) and events (what happened when syncing)."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.integration import IntegrationConnection, IntegrationEvent, IntegrationLink


async def get_link(db: AsyncSession, conn: IntegrationConnection, entity: str, local_key) -> IntegrationLink | None:
    return await db.scalar(select(IntegrationLink).where(
        IntegrationLink.connection_id == conn.id, IntegrationLink.entity == entity,
        IntegrationLink.local_key == str(local_key),
    ))


async def links(db: AsyncSession, conn: IntegrationConnection, entity: str, local_keys) -> dict[str, IntegrationLink]:
    keys = [str(k) for k in local_keys]
    if not keys:
        return {}
    rows = await db.scalars(select(IntegrationLink).where(
        IntegrationLink.connection_id == conn.id, IntegrationLink.entity == entity, IntegrationLink.local_key.in_(keys),
    ))
    return {r.local_key: r for r in rows}


async def save_link(db: AsyncSession, conn: IntegrationConnection, entity: str, local_key, external_id,
                    *, external_ref: str | None = None, extra: dict | None = None) -> IntegrationLink:
    link = await get_link(db, conn, entity, local_key)
    if link is None:
        link = IntegrationLink(tenant_id=conn.tenant_id, connection_id=conn.id, entity=entity, local_key=str(local_key),
                               external_id=str(external_id), external_ref=external_ref, extra=extra or {})
        db.add(link)
    else:
        link.external_id = str(external_id)
        if external_ref is not None:
            link.external_ref = external_ref
        if extra is not None:
            link.extra = {**(link.extra or {}), **extra}
    await db.flush()
    return link


async def record(db: AsyncSession, conn: IntegrationConnection, *, direction: str, action: str, local_key,
                 label: str, status: str, message: str | None = None, external_ref: str | None = None,
                 details: dict | None = None, count_attempt: bool = True) -> None:
    """Upsert the one event line for this action and record (a new line per catalog pull)."""
    values = dict(
        id=uuid.uuid4(), tenant_id=conn.tenant_id, connection_id=conn.id, direction=direction, action=action,
        local_key=str(local_key), label=label[:120], status=status, message=(message or None) and message[:2000],
        external_ref=external_ref, attempts=1 if count_attempt else 0, details=details or {},
    )
    update = dict(status=status, message=values["message"], label=values["label"], details=values["details"])
    if external_ref is not None:
        update["external_ref"] = external_ref
    stmt = insert(IntegrationEvent).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_integration_event_item",
        set_={**update, "attempts": IntegrationEvent.attempts + (1 if count_attempt else 0), "updated_at": func.now()},
    )
    await db.execute(stmt)