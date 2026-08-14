import uuid

from fastapi import APIRouter, Depends, status

from app.core.deps import CurrentUser, DBSession, require_role
from app.core.enums import UserRole
from app.modules.orders import service
from app.schemas.order import (
    EscalationOut,
    OrderCreate,
    OrderOut,
    ResolveEscalation,
)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=list[OrderOut])
async def list_orders(db: DBSession, user: CurrentUser) -> list[OrderOut]:
    return await service.list_orders(db, user.tenant_id)


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(data: OrderCreate, db: DBSession, user: CurrentUser) -> OrderOut:
    """Create an order (cart). Confirms if all items are in stock, otherwise
    holds for human review and opens an escalation."""
    return await service.create_order(db, user.tenant_id, data, actor_id=user.id)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: uuid.UUID, db: DBSession, user: CurrentUser) -> OrderOut:
    return await service.get_order(db, user.tenant_id, order_id)


# --- escalations (human review queue) ---
@router.get("/escalations/open", response_model=list[EscalationOut])
async def open_escalations(db: DBSession, user: CurrentUser) -> list[EscalationOut]:
    return await service.list_escalations(db, user.tenant_id, open_only=True)


@router.post(
    "/escalations/{escalation_id}/resolve",
    response_model=EscalationOut,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def resolve_escalation(
    escalation_id: uuid.UUID,
    data: ResolveEscalation,
    db: DBSession,
    user: CurrentUser,
) -> EscalationOut:
    """Admin approves (fulfil what stock allows) or rejects (cancel) a held order."""
    return await service.resolve_escalation(
        db, user.tenant_id, escalation_id, approve=data.approve, note=data.note, actor_id=user.id
    )