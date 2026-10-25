import json
import logging

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.channels.whatsapp import service
from app.config import settings
from app.db.session import SessionLocal
from app.jobs.queue import WHATSAPP_INBOUND_AUDIO, WHATSAPP_INBOUND_TEXT, enqueue

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])
logger = logging.getLogger("salesman.whatsapp")


@router.get("")
async def verify(request: Request):
    """Meta calls this once to verify the webhook. Echo back hub.challenge if the
    verify token matches ours."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    if mode == "subscribe" and token and token == settings.WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(content=challenge or "")
    return Response(status_code=status.HTTP_403_FORBIDDEN)


@router.post("")
async def receive(request: Request):
    """Receive inbound WhatsApp events.

    Only verifies the signature and queues each message, then returns 200
    straight away. The AI agent runs in the job worker, so Meta never times
    out waiting for us and re-delivers the same message. Each message is
    queued under its WhatsApp id, so a re-delivery is ignored.
    """
    raw = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not service.verify_signature(raw, signature):
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "ignored"}

    queued = 0
    async with SessionLocal() as db:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                metadata = value.get("metadata", {})
                phone_number_id = metadata.get("phone_number_id")
                messages = value.get("messages", [])
                contacts = value.get("contacts", [])
                profile_name = None
                if contacts:
                    profile_name = contacts[0].get("profile", {}).get("name")

                for msg in messages:
                    mtype = msg.get("type")
                    from_number = msg.get("from")
                    wa_message_id = msg.get("id")
                    if not (phone_number_id and from_number):
                        continue

                    base = {
                        "phone_number_id": phone_number_id,
                        "from_number": from_number,
                        "wa_message_id": wa_message_id,
                        "profile_name": profile_name,
                    }
                    dedupe = f"wa-in:{wa_message_id}" if wa_message_id else None

                    if mtype == "text":
                        text = msg.get("text", {}).get("body", "")
                        if not text:
                            continue
                        if await enqueue(db, WHATSAPP_INBOUND_TEXT, {**base, "text": text}, dedupe_key=dedupe):
                            queued += 1
                    elif mtype == "audio":
                        media_id = msg.get("audio", {}).get("id")
                        if not media_id:
                            continue
                        if await enqueue(db, WHATSAPP_INBOUND_AUDIO, {**base, "media_id": media_id}, dedupe_key=dedupe):
                            queued += 1
                    # other types (image, document, etc.) ignored for now

    if queued:
        logger.info("whatsapp messages queued", extra={"ctx_count": queued})
    return {"status": "received"}