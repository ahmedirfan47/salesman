"""Job handlers. Each one receives a fresh DB session and the job payload."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.whatsapp import service as whatsapp
from app.db.models.tenant import Tenant
from app.jobs.queue import WHATSAPP_INBOUND_AUDIO, WHATSAPP_INBOUND_TEXT, WHATSAPP_SEND_TEXT
from app.jobs.worker import handler


@handler(WHATSAPP_INBOUND_TEXT)
async def inbound_text(db: AsyncSession, p: dict) -> None:
    await whatsapp.process_incoming(
        db, p["phone_number_id"], p["from_number"], p["text"], p.get("wa_message_id"), p.get("profile_name")
    )


@handler(WHATSAPP_INBOUND_AUDIO)
async def inbound_audio(db: AsyncSession, p: dict) -> None:
    await whatsapp.process_incoming_audio(
        db, p["phone_number_id"], p["from_number"], p["media_id"], p.get("wa_message_id"), p.get("profile_name")
    )


@handler(WHATSAPP_SEND_TEXT)
async def send_text(db: AsyncSession, p: dict) -> None:
    tenant = await db.get(Tenant, uuid.UUID(p["tenant_id"]))
    if tenant is None:
        return
    await whatsapp.send_text(tenant, p["to"], p["body"])