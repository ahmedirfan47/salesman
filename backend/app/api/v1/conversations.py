import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.deps import CurrentUser, DBSession
from app.db.models.conversation import Conversation
from app.db.models.message import Message
from app.schemas.conversation import ConversationOut, MessageOut

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(db: DBSession, user: CurrentUser) -> list[ConversationOut]:
    rows = await db.scalars(
        select(Conversation)
        .where(Conversation.tenant_id == user.tenant_id)
        .order_by(Conversation.last_message_at.desc().nullslast())
    )
    return list(rows)


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: uuid.UUID, db: DBSession, user: CurrentUser
) -> list[MessageOut]:
    conv = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.tenant_id == user.tenant_id
        )
    )
    if not conv:
        raise HTTPException(404, "Conversation not found")
    rows = await db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return list(rows)