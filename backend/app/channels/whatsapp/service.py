"""WhatsApp Cloud API integration.

Each branch has its own WhatsApp number. An inbound message is routed to the
branch that owns the receiving number, so the AI quotes that branch's prices
and stock and the order is placed at that branch.

- verify_signature: confirm a POST really came from Meta (HMAC on the raw body)
- send_text / send_template: message a customer from a branch's number
- process_incoming: route an inbound text message to its branch, run the AI
  agent, persist the conversation, and queue the reply for sending.
- process_incoming_audio: download a voice note, transcribe it, then reuse the
  text pipeline.

Both inbound functions run from the job queue (see app.jobs), never inside the
webhook request, and are idempotent per WhatsApp message id: if Meta delivers
the same message twice, it is answered once.
"""
import hashlib
import hmac
import logging
import re
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agent import run_agent
from app.ai.transcribe import transcribe
from app.config import settings
from app.db.models.branch import Branch
from app.db.models.conversation import Conversation
from app.db.models.message import Message
from app.db.models.tenant import Tenant
from app.jobs.queue import WHATSAPP_SEND_TEXT, enqueue

_HISTORY_LIMIT = 12
_FALLBACK_REPLY = "Sorry, I couldn't process that. A team member will follow up."
_ARABIC = re.compile(r"[؀-ۿ]")

logger = logging.getLogger("salesman.whatsapp")


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


async def _post_message(branch: Branch, payload: dict) -> dict:
    if not branch.whatsapp_phone_number_id or not branch.whatsapp_access_token:
        return {"skipped": "branch WhatsApp not configured"}
    url = f"{settings.WHATSAPP_API_BASE}/{branch.whatsapp_phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {branch.whatsapp_access_token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json={"messaging_product": "whatsapp", **payload}, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def send_text(branch: Branch, to_number: str, body: str) -> dict:
    """Send a WhatsApp text message from a branch's number."""
    return await _post_message(branch, {"to": to_number, "type": "text", "text": {"body": body[:4096]}})


async def send_template(branch: Branch, to_number: str, name: str, language: str, params: list[str]) -> dict:
    """Send a Meta-approved template (needed outside the 24-hour customer-service window)."""
    clean = [re.sub(r"\s+", " ", p).strip()[:1000] or "-" for p in params]  # no newlines allowed in params
    return await _post_message(branch, {
        "to": to_number,
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": language},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in clean]}],
        },
    })


async def branch_for_number(db: AsyncSession, phone_number_id: str) -> tuple[Branch, Tenant] | None:
    branch = await db.scalar(
        select(Branch).where(Branch.whatsapp_phone_number_id == phone_number_id, Branch.is_active.is_(True))
    )
    if branch is None:
        return None
    tenant = await db.get(Tenant, branch.tenant_id)
    return branch, tenant


async def _get_or_create_conversation(
    db: AsyncSession, branch: Branch, customer_number: str, name: str | None
) -> Conversation:
    conv = await db.scalar(
        select(Conversation)
        .where(
            Conversation.tenant_id == branch.tenant_id,
            Conversation.branch_id == branch.id,
            Conversation.customer_number == customer_number,
            Conversation.status == "active",
        )
        .order_by(Conversation.created_at.desc())
    )
    if conv:
        return conv
    conv = Conversation(
        tenant_id=branch.tenant_id, branch_id=branch.id, customer_number=customer_number,
        customer_name=name, status="active",
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


async def _already_handled(db: AsyncSession, tenant_id: uuid.UUID, wa_message_id: str | None) -> bool:
    if not wa_message_id:
        return False
    found = await db.scalar(
        select(Message.id).where(
            Message.tenant_id == tenant_id,
            Message.wa_message_id == wa_message_id,
            Message.direction == "in",
        )
    )
    return found is not None


async def queue_reply(db: AsyncSession, branch: Branch, to_number: str, body: str) -> None:
    """Send via the job queue so a temporary Meta/API outage is retried, not lost."""
    await enqueue(
        db,
        WHATSAPP_SEND_TEXT,
        {"tenant_id": str(branch.tenant_id), "branch_id": str(branch.id), "to": to_number, "body": body},
        tenant_id=branch.tenant_id,
        max_attempts=5,
    )


async def _download_media(branch: Branch, media_id: str) -> tuple[bytes, str] | None:
    """Fetch a WhatsApp media file: first resolve the media URL, then download it.
    Returns (bytes, filename) or None."""
    if not branch.whatsapp_access_token:
        return None
    headers = {"Authorization": f"Bearer {branch.whatsapp_access_token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        meta = await client.get(f"{settings.WHATSAPP_API_BASE}/{media_id}", headers=headers)
        meta.raise_for_status()
        info = meta.json()
        url = info.get("url")
        mime = info.get("mime_type", "audio/ogg")
        if not url:
            return None
        audio = await client.get(url, headers=headers)
        audio.raise_for_status()
        ext = "ogg"
        if "mp4" in mime or "m4a" in mime:
            ext = "m4a"
        elif "mpeg" in mime or "mp3" in mime:
            ext = "mp3"
        elif "wav" in mime:
            ext = "wav"
        return audio.content, f"voice.{ext}"


async def process_incoming_audio(
    db: AsyncSession,
    phone_number_id: str,
    from_number: str,
    media_id: str,
    wa_message_id: str | None,
    profile_name: str | None = None,
) -> None:
    """Voice-note pipeline: download audio -> transcribe -> reuse the text pipeline."""
    found = await branch_for_number(db, phone_number_id)
    if not found:
        return
    branch, tenant = found
    if await _already_handled(db, tenant.id, wa_message_id):
        return
    media = await _download_media(branch, media_id)
    if not media:
        return
    audio_bytes, filename = media
    try:
        text = await transcribe(audio_bytes, filename)
    except Exception:  # noqa: BLE001
        logger.exception("voice note transcription failed", extra={"ctx_tenant_id": str(tenant.id)})
        text = ""
    if not text:
        conv = await _get_or_create_conversation(db, branch, from_number, profile_name)
        db.add(Message(
            tenant_id=tenant.id, conversation_id=conv.id, direction="in",
            sender="customer", msg_type="audio", content="[voice note - could not transcribe]",
            wa_message_id=wa_message_id,
        ))
        await db.commit()
        await queue_reply(
            db, branch, from_number,
            "Sorry, I couldn't understand that voice note. Could you type your message or send it again?",
        )
        return

    await process_incoming(
        db, phone_number_id, from_number, text, wa_message_id, profile_name,
        inbound_type="audio",
    )


async def process_incoming(
    db: AsyncSession,
    phone_number_id: str,
    from_number: str,
    text: str,
    wa_message_id: str | None,
    profile_name: str | None = None,
    inbound_type: str = "text",
) -> None:
    """Full inbound pipeline for one message (text, or a transcribed voice note)."""
    found = await branch_for_number(db, phone_number_id)
    if not found:
        return
    branch, tenant = found
    if await _already_handled(db, tenant.id, wa_message_id):
        return

    conv = await _get_or_create_conversation(db, branch, from_number, profile_name)

    history = await _history(db, conv.id)

    now = datetime.now(timezone.utc)
    db.add(Message(
        tenant_id=tenant.id, conversation_id=conv.id, direction="in",
        sender="customer", msg_type=inbound_type, content=text, wa_message_id=wa_message_id,
    ))
    conv.last_message_at = now
    conv.language = "ar" if _ARABIC.search(text) else "en"  # order updates follow this
    await db.commit()

    tenant_id, branch_id, conv_id, business = tenant.id, branch.id, conv.id, tenant.name
    try:
        result = await run_agent(
            db, tenant_id, business, history, text, branch_id=branch_id, customer_number=from_number,
        )
        reply = result.get("reply") or _FALLBACK_REPLY
    except Exception:  # noqa: BLE001 -- the customer always gets an answer
        logger.exception("AI agent failed", extra={"ctx_tenant_id": str(tenant_id)})
        await db.rollback()
        reply = _FALLBACK_REPLY
    # the agent may commit or roll back; reload before touching attributes
    branch = await db.get(Branch, branch_id)
    conv = await db.get(Conversation, conv_id)

    db.add(Message(
        tenant_id=tenant_id, conversation_id=conv.id, direction="out",
        sender="ai", content=reply,
    ))
    conv.last_message_at = datetime.now(timezone.utc)
    await db.commit()

    await queue_reply(db, branch, from_number, reply)