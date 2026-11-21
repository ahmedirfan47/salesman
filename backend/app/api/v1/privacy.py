"""Data protection: full export, erasing a customer, message retention and the log of what was done."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.deps import CurrentUser, DBSession, require_role
from app.core.enums import UserRole
from app.modules.privacy import service

router = APIRouter(prefix="/privacy", tags=["privacy"], dependencies=[Depends(require_role(UserRole.ADMIN))])


class EraseIn(BaseModel):
    confirm: bool = False


@router.get("/export")
async def export(db: DBSession, user: CurrentUser) -> Response:
    """Everything this business has in Salesman, as a ZIP of JSON files (no passwords or keys)."""
    data = await service.export(db, user.tenant_id, actor_id=user.id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="salesman-export-{stamp}.zip"'})


@router.post("/customers/{customer_id}/erase")
async def erase_customer(customer_id: uuid.UUID, data: EraseIn, db: DBSession, user: CurrentUser) -> dict:
    """Remove a customer's personal data (a PDPL erasure request). Issued tax invoices are kept as the law requires."""
    if not data.confirm:
        from fastapi import HTTPException

        raise HTTPException(422, "Send confirm: true to erase. This can't be undone.")
    return await service.erase_customer(db, user.tenant_id, customer_id, actor_id=user.id)


@router.post("/retention/run")
async def run_retention(db: DBSession, user: CurrentUser) -> dict:
    """Apply the message-retention period now (it also runs every hour)."""
    return {"messages_deleted": await service.apply_retention(db, user.tenant_id)}


@router.get("/requests")
async def requests(db: DBSession, user: CurrentUser) -> list[dict]:
    return await service.list_requests(db, user.tenant_id)
