"""Job handlers. Each one receives a fresh DB session and the job payload."""
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.whatsapp import service as whatsapp
from app.core.branches import default_branch
from app.db.models.branch import Branch
from app.jobs.queue import (
    WHATSAPP_INBOUND_AUDIO,
    WHATSAPP_INBOUND_TEXT,
    WHATSAPP_ORDER_UPDATE,
    WHATSAPP_SEND_DOCUMENT,
    WHATSAPP_SEND_TEXT,
    ZATCA_SUBMIT,
)
from app.jobs.worker import handler
from app.modules.accounts import documents as account_documents
from app.modules.notifications import service as notifications
from app.modules.zatca import service as zatca

logger = logging.getLogger("salesman.jobs")


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
    if p.get("branch_id"):
        branch = await db.get(Branch, uuid.UUID(p["branch_id"]))
    else:  # replies queued before branches existed
        branch = await default_branch(db, uuid.UUID(p["tenant_id"]))
    if branch is None:
        return
    await whatsapp.send_text(branch, p["to"], p["body"])


@handler(WHATSAPP_ORDER_UPDATE)
async def order_update(db: AsyncSession, p: dict) -> None:
    result = await notifications.send_order_update(db, p)
    if result.startswith("skipped"):
        logger.info("order update not sent", extra={"ctx_order_id": p.get("order_id"), "ctx_reason": result[8:]})


@handler(WHATSAPP_SEND_DOCUMENT)
async def send_document(db: AsyncSession, p: dict) -> None:
    """Build a statement or invoice PDF at send time (so it is current) and send it."""
    branch = await db.get(Branch, uuid.UUID(p["branch_id"]))
    if branch is None:
        return
    built = await account_documents.build(db, p)
    if built is None:
        logger.info("document not sent", extra={"ctx_kind": p.get("doc")})
        return
    content, filename, caption = built
    await whatsapp.send_document(branch, p["to"], content, filename, caption)


@handler(ZATCA_SUBMIT)
async def zatca_submit(db: AsyncSession, p: dict) -> None:
    """Clear or report one e-invoice. ZATCA being unreachable raises, so the queue retries it."""
    result = await zatca.submit_document(db, uuid.UUID(p["document_id"]))
    logger.info("zatca submission", extra={"ctx_document_id": p["document_id"], "ctx_result": result})