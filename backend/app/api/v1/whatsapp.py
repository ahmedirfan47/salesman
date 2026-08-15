import json

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.channels.whatsapp import service
from app.config import settings
from app.db.session import SessionLocal

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])


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
    """Receive inbound WhatsApp events, verify signature, process messages."""
    raw = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not service.verify_signature(raw, signature):
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "ignored"}

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
                if msg.get("type") != "text":
                    continue  # non-text handled later (voice module)
                from_number = msg.get("from")
                text = msg.get("text", {}).get("body", "")
                wa_message_id = msg.get("id")
                if not (phone_number_id and from_number and text):
                    continue
                async with SessionLocal() as db:
                    await service.process_incoming(
                        db, phone_number_id, from_number, text, wa_message_id, profile_name
                    )

    return {"status": "received"}