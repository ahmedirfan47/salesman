from fastapi import APIRouter

from app.ai.agent import run_agent
from app.core.branches import BranchScope, resolve_branch
from app.core.deps import CurrentUser, DBSession
from app.db.models.tenant import Tenant
from app.schemas.agent import ChatRequest, ChatResponse

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