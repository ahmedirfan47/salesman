"""The one function the rest of Salesman calls when something an ERP should know about happens.

It only queues a job (inside the caller's transaction unless told to
commit), so an ERP being slow, down or misconfigured never slows down or
breaks taking orders, invoicing or recording payments. It does nothing when
the business has no active connection.
"""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.integration import IntegrationConnection
from app.jobs.queue import ERP_PUSH, enqueue

logger = logging.getLogger("salesman.integrations")

PUSH_ATTEMPTS = 8   # with the queue's backoff: about 35 minutes of retries for a temporary outage

# what is sent: order.confirmed | order.delivered | order.cancelled | invoice | payment | payment.void | customer
ACTIONS = ("order.confirmed", "order.delivered", "order.cancelled", "invoice", "payment", "payment.void", "customer")


async def active_connection_id(db: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID | None:
    return await db.scalar(
        select(IntegrationConnection.id).where(
            IntegrationConnection.tenant_id == tenant_id, IntegrationConnection.status == "active",
        )
    )


async def queue(db: AsyncSession, tenant_id: uuid.UUID, action: str, record_id: uuid.UUID, *,
                commit: bool = False, retry: int = 0) -> bool:
    """Queue `action` for one record. Returns False when there is nothing to do."""
    if action not in ACTIONS:
        raise ValueError(f"Unknown ERP action {action}")
    connection_id = await active_connection_id(db, tenant_id)
    if connection_id is None:
        return False
    suffix = f":retry{retry}" if retry else ""
    return await enqueue(
        db, ERP_PUSH, {"connection_id": str(connection_id), "action": action, "id": str(record_id)},
        tenant_id=tenant_id, dedupe_key=f"erp:{connection_id}:{action}:{record_id}{suffix}",
        max_attempts=PUSH_ATTEMPTS, commit=commit,
    )


async def queue_safely(db: AsyncSession, tenant_id: uuid.UUID, action: str, record_id: uuid.UUID) -> None:
    """For calls made after the caller's own commit: never raises."""
    try:
        await queue(db, tenant_id, action, record_id, commit=True)
    except Exception:  # noqa: BLE001
        logger.exception("could not queue ERP sync", extra={"ctx_action": action, "ctx_record_id": str(record_id)})
        await db.rollback()