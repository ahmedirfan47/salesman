import uuid

from fastapi import APIRouter, Depends, status

from app.core.deps import CurrentUser, DBSession, require_role
from app.core.enums import UserRole
from app.modules.orders import service
from app.schemas.order import (
    EscalationOut,
    OrderCreate,
    OrderDetailOut,
    OrderEventOut,
    OrderOut,
    OrderTransition,
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


@router.get("/{order_id}", response_model=OrderDetailOut)
async def get_order(order_id: uuid.UUID, db: DBSession, user: CurrentUser) -> OrderDetailOut:
    order = await service.get_order(db, user.tenant_id, order_id)
    events = await service.list_order_events(db, user.tenant_id, order_id)
    data = OrderDetailOut.model_validate(order)
    data.events = [OrderEventOut.model_validate(e) for e in events]
    return data


@router.post("/{order_id}/transition", response_model=OrderOut)
async def transition_order(
    order_id: uuid.UUID, data: OrderTransition, db: DBSession, user: CurrentUser
) -> OrderOut:
    """Advance an order through its lifecycle: confirmed -> dispatched ->
    delivered -> completed (or cancel). Records who moved it and when."""
    actor_name = getattr(user, "full_name", None) or getattr(user, "email", None)
    return await service.transition_order(
        db, user.tenant_id, order_id, data.to_status,
        actor_id=user.id, actor_name=actor_name, note=data.note,
    )


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