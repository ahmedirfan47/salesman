"""The reorder agent: who is due, what was sent and what it brought in. Settings live under /agent/settings."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.core.deps import CurrentUser, DBSession, require_capability
from app.core.permissions import Capability
from app.modules.reorder import service

router = APIRouter(prefix="/reorder", tags=["reorder"])


@router.get("", dependencies=[Depends(require_capability(Capability.VIEW_REPORTS))])
async def overview(db: DBSession, user: CurrentUser) -> dict:
    return await service.overview(db, user.tenant_id)


@router.post("/run", dependencies=[Depends(require_capability(Capability.MANAGE_PRICING))])
async def run_now(db: DBSession, user: CurrentUser) -> dict:
    """Queue the messages due now (still only to customers who are due, once each)."""
    return {"queued": await service.queue_due(db, user.tenant_id, now=datetime.now(timezone.utc), ignore_hours=True)}
