from fastapi import APIRouter, Depends

from app.ai.agent import run_agent
from app.core.branches import BranchScope, resolve_branch
from app.core.deps import CurrentUser, DBSession, require_capability
from app.core.permissions import Capability
from app.db.models.tenant import Tenant
from app.modules.orders import review
from app.schemas.agent import AgentSettingsIn, AgentSettingsOut, ChatRequest, ChatResponse

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat", response_model=ChatResponse)
async def chat(data: ChatRequest, db: DBSession, user: CurrentUser, scope: BranchScope) -> ChatResponse:
    """Talk to the AI sales agent as if you were a customer (dev/testing endpoint).

    Uses the branch selected in the dashboard (or your own branch, or the
    default branch). Real customers reach the agent through WhatsApp.
    """
    tenant = await db.get(Tenant, user.tenant_id)
    business_name = tenant.name if tenant else "our store"
    branch_id = await resolve_branch(db, user.tenant_id, scope)
    result = await run_agent(
        db,
        user.tenant_id,
        business_name,
        history=[m.model_dump() for m in data.history],
        user_message=data.message,
        branch_id=branch_id,
    )
    return ChatResponse(**result)


def _settings_out(row) -> AgentSettingsOut:
    return AgentSettingsOut(
        review_min_confidence=float(row.review_min_confidence), review_quantity_multiple=row.review_quantity_multiple,
        learn_aliases=row.learn_aliases, review_all_ai_orders=row.review_all_ai_orders,
        reorder_enabled=row.reorder_enabled, reorder_factor=float(row.reorder_factor),
        reorder_min_orders=row.reorder_min_orders, reorder_template=row.reorder_template,
        message_retention_days=row.message_retention_days,
    )


@router.get("/settings", response_model=AgentSettingsOut)
async def get_settings(db: DBSession, user: CurrentUser) -> AgentSettingsOut:
    """How cautious the AI is: when it holds an order for the team to check."""
    row = await review.get_settings(db, user.tenant_id)
    await db.commit()
    return _settings_out(row)


@router.put("/settings", response_model=AgentSettingsOut,
            dependencies=[Depends(require_capability(Capability.MANAGE_PRODUCTS))])
async def update_settings(data: AgentSettingsIn, db: DBSession, user: CurrentUser) -> AgentSettingsOut:
    return _settings_out(await review.update_settings(db, user.tenant_id, data.model_dump(exclude_unset=True)))
