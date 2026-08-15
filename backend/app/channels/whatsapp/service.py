"""WhatsApp Cloud API integration.

- verify_signature: confirm a POST really came from Meta (HMAC on the raw body)
- send_text: reply to a customer via the Graph API
- process_incoming: route an inbound message to the tenant, run the AI agent,
  send the reply, and persist the conversation.
"""
import hashlib
import hmac
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent import run_agent
from app.config import settings
from app.db.models.conversation import Conversation
from app.db.models.message import Message
from app.db.models.tenant import Tenant

_HISTORY_LIMIT = 12


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Validate Meta's X-Hub-Signature-256 header against the app secret.

    If no app secret is configured (pre-setup / local dev), we allow the request
    so the endpoint is testable; in production you MUST set WHATSAPP_APP_SECRET.
    """
    if not settings.WHATSAPP_APP_SECRET:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    provided = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, provided)


async def send_text(tenant: Tenant, to_number: str, body: str) -> dict:
    """Send a WhatsApp text message via the Graph API using the tenant's creds."""
    if not tenant.whatsapp_phone_number_id or not tenant.whatsapp_access_token:
        return {"skipped": "tenant WhatsApp not configured"}
    url = f"{settings.WHATSAPP_API_BASE}/{tenant.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": body[:4096]},
    }
    headers = {"Authorization": f"Bearer {tenant.whatsapp_access_token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _get_or_create_conversation(
    db: AsyncSession, tenant_id: uuid.UUID, customer_number: str, name: str | None
) -> Conversation:
    conv = await db.scalar(
        select(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.customer_number == customer_number,
            Conversation.status == "active",
        )
        .order_by(Conversation.created_at.desc())
    )
    if conv:
        return conv
    conv = Conversation(
        tenant_id=tenant_id, customer_number=customer_number, customer_name=name, status="active"
    )
    db.add(conv)
    await db.flush()
    return conv


async def _history(db: AsyncSession, conversation_id: uuid.UUID) -> list[dict]:
    msgs = list(
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(_HISTORY_LIMIT)
        )
    )
    msgs.reverse()
    return [
        {"role": "user" if m.direction == "in" else "assistant", "content": m.content}
        for m in msgs
    ]


async def process_incoming(
    db: AsyncSession,
    phone_number_id: str,
    from_number: str,
    text: str,
    wa_message_id: str | None,
    profile_name: str | None = None,
) -> None:
    """Full inbound pipeline for one text message."""
    tenant = await db.scalar(
        select(Tenant).where(Tenant.whatsapp_phone_number_id == phone_number_id)
    )
    if not tenant:
        # no tenant owns this WhatsApp number; ignore
        return

    conv = await _get_or_create_conversation(db, tenant.id, from_number, profile_name)

    # build history BEFORE storing the new inbound message
    history = await _history(db, conv.id)

    now = datetime.now(timezone.utc)
    db.add(Message(
        tenant_id=tenant.id, conversation_id=conv.id, direction="in",
        sender="customer", content=text, wa_message_id=wa_message_id,
    ))
    conv.last_message_at = now
    await db.commit()

    # run the agent
    result = await run_agent(db, tenant.id, tenant.name, history, text)
    reply = result.get("reply") or "Sorry, I couldn't process that. A team member will follow up."

    # store + send the reply
    db.add(Message(
        tenant_id=tenant.id, conversation_id=conv.id, direction="out",
        sender="ai", content=reply,
    ))
    conv.last_message_at = datetime.now(timezone.utc)
    await db.commit()

    await send_text(tenant, from_number, reply)