"""Job handlers. Each one receives a fresh DB session and the job payload."""
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.whatsapp import service as whatsapp
from app.core.branches import default_branch
from app.db.models.branch import Branch
from app.jobs.queue import (
    ERP_PULL,
    ERP_PUSH,
    WHATSAPP_COLLECTION_REMINDER,
    WHATSAPP_REORDER_NUDGE,
    WHATSAPP_INBOUND_AUDIO,
    WHATSAPP_INBOUND_TEXT,
    WHATSAPP_ORDER_UPDATE,
    WHATSAPP_SEND_DOCUMENT,
    WHATSAPP_SEND_TEXT,
    ZATCA_SUBMIT,
)
from app.jobs.worker import handler
from app.modules.accounts import documents as account_documents
from app.modules.collections import service as collections
from app.modules.integrations import service as integrations
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


@handler(ERP_PUSH)
async def erp_push(db: AsyncSession, p: dict) -> None:
    """Send one order, invoice, payment or customer to the connected ERP. Raises only to be retried."""
    result = await integrations.run_push(db, p)
    logger.info("erp push", extra={"ctx_action": p.get("action"), "ctx_record_id": p.get("id"), "ctx_result": result})


@handler(ERP_PULL)
async def erp_pull(db: AsyncSession, p: dict) -> None:
    """Refresh products, prices and stock from the connected ERP."""
    result = await integrations.run_pull(db, p)
    logger.info("erp pull", extra={"ctx_connection_id": p.get("connection_id"), "ctx_result": result})

@handler(WHATSAPP_REORDER_NUDGE)
async def reorder_nudge(db: AsyncSession, p: dict) -> None:
    """Send one reorder message. A Meta outage raises, so the queue retries it."""
    from app.modules.reorder import service as reorder

    result = await reorder.send_nudge(db, uuid.UUID(p["nudge_id"]))
    logger.info("reorder nudge", extra={"ctx_nudge_id": p["nudge_id"], "ctx_result": result})


@handler(WHATSAPP_COLLECTION_REMINDER)
async def collection_reminder(db: AsyncSession, p: dict) -> None:
    """Send one payment reminder. A Meta outage raises, so the queue retries it."""
    result = await collections.send_reminder(db, uuid.UUID(p["reminder_id"]))
    logger.info("collection reminder", extra={"ctx_reminder_id": p["reminder_id"], "ctx_result": result})
