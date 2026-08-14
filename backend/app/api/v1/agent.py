from app.ai.agent import run_agent
from app.core.deps import CurrentUser, DBSession
from app.db.models.tenant import Tenant
from app.schemas.agent import ChatRequest, ChatResponse
from fastapi import APIRouter

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat", response_model=ChatResponse)
async def chat(data: ChatRequest, db: DBSession, user: CurrentUser) -> ChatResponse:
    """Talk to the AI sales agent as if you were a customer (dev/testing endpoint).

    Later, the WhatsApp layer will call run_agent() with the customer's messages
    instead of this authenticated endpoint.
    """
    tenant = await db.get(Tenant, user.tenant_id)
    business_name = tenant.name if tenant else "our store"
    result = await run_agent(
        db,
        user.tenant_id,
        business_name,
        history=[m.model_dump() for m in data.history],
        user_message=data.message,
    )
    return ChatResponse(**result)