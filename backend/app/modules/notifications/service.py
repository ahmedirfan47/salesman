"""WhatsApp order updates.

When an order is dispatched, delivered or cancelled, or a held order is
approved or rejected, the customer gets a WhatsApp message from the branch's
number, in their language.

WhatsApp only allows free-form messages within 24 hours of the customer's
last message. Outside that window a business may only send a Meta-approved
template, so each branch can name one (Branches page). Without a template,
an update outside the window is skipped and logged rather than failing.

Updates are sent through the job queue, so a Meta outage is retried, and each
(order, event) pair is sent at most once.
"""
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.branch import Branch
from app.db.models.conversation import Conversation
from app.db.models.message import Message
from app.db.models.order import Order
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.jobs.queue import WHATSAPP_ORDER_UPDATE, enqueue

logger = logging.getLogger("salesman.notifications")

# order statuses that trigger an update; "approved"/"rejected" come from held orders
STATUS_EVENTS = {"dispatched", "delivered", "cancelled"}
EVENTS = STATUS_EVENTS | {"approved", "rejected"}

# send free text only with a safety margin inside Meta's 24-hour window
_WINDOW = timedelta(hours=23, minutes=50)
_ARABIC = re.compile(r"[\u0600-\u06FF]")
_CCY_AR = {"SAR": "ر.س", "AED": "د.إ", "PKR": "روبية", "USD": "دولار"}

# Suggested template to submit in Meta (category: Utility), in English (en) and Arabic (ar):
TEMPLATE_HINT = {
    "en": "Hello {{1}}, an update on your order {{2}}: {{3}}. Reply to this message if you have any questions.",
    "ar": "مرحباً {{1}}، تحديث بخصوص طلبك {{2}}: {{3}}. رد على هذه الرسالة لأي استفسار.",
}


async def queue_order_update(db: AsyncSession, order: Order, event: str, extra: dict | None = None) -> bool:
    """Queue one update. Returns False when there's nobody to tell or it was already queued."""
    if event not in EVENTS or not order.whatsapp_number:
        return False
    payload = {"order_id": str(order.id), "event": event, **(extra or {})}
    return await enqueue(
        db, WHATSAPP_ORDER_UPDATE, payload, tenant_id=order.tenant_id,
        dedupe_key=f"order-update:{order.id}:{event}", max_attempts=5,
    )


def _digits(number: str | None) -> str:
    return re.sub(r"\D", "", number or "")


def _money(amount, currency: str, language: str) -> str:
    value = Decimal(str(amount))
    text = f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"
    return f"{text} {_CCY_AR.get(currency, currency)}" if language == "ar" else f"{currency} {text}"


def render(event: str, order: Order, language: str, *, business: str, driver: str | None,
           shorted: list[dict] | None = None) -> tuple[str, str]:
    """Returns (full message for the 24-hour window, short phrase for the template's {{3}})."""
    num = order.order_number
    total = _money(order.total_amount, order.currency, language)
    shorted = shorted or []
    if language == "ar":
        if event == "dispatched":
            who = f" مع السائق {driver}" if driver else ""
            return f"🚚 طلبك رقم {num} في الطريق إليك{who}.", "طلبك في الطريق إليك"
        if event == "delivered":
            return f"✅ تم توصيل طلبك رقم {num}. شكراً لتعاملك مع {business}!", "تم توصيل طلبك"
        if event == "cancelled":
            return (f"تم إلغاء طلبك رقم {num}. إذا لم تكن تتوقع ذلك، رد على هذه الرسالة.",
                    "تم إلغاء الطلب")
        if event == "approved":
            text = f"✅ تم تأكيد طلبك رقم {num}. الإجمالي: {total}."
            if shorted:
                parts = "، ".join(f"{s['name']} {s['supplied']} من {s['requested']}" for s in shorted)
                text += f" وفّرنا جزءاً من الكمية فقط: {parts}."
            return text, f"تم تأكيد الطلب، الإجمالي {total}"
        return (f"نعتذر، لا نستطيع تنفيذ طلبك رقم {num} حالياً. سيتواصل معك أحد أفراد الفريق قريباً.",
                "لا نستطيع تنفيذ الطلب حالياً")

    if event == "dispatched":
        who = f" with {driver}" if driver else ""
        return f"🚚 Your order {num} is on its way{who}.", "it is on its way"
    if event == "delivered":
        return f"✅ Your order {num} has been delivered. Thank you for ordering with {business}!", "it has been delivered"
    if event == "cancelled":
        return (f"Your order {num} has been cancelled. If you didn't expect this, just reply to this message.",
                "it has been cancelled")
    if event == "approved":
        text = f"✅ Good news: your order {num} is confirmed. Total: {total}."
        if shorted:
            parts = "; ".join(f"{s['name']} {s['supplied']} of {s['requested']}" for s in shorted)
            text += f" We could only supply part of it: {parts}."
        return text, f"it is confirmed, total {total}"
    return (f"Sorry, we can't fulfil your order {num} right now. A team member will contact you shortly.",
            "we can't fulfil it right now")


async def _conversation(db: AsyncSession, order: Order) -> Conversation | None:
    digits = _digits(order.whatsapp_number)
    return await db.scalar(
        select(Conversation)
        .where(
            Conversation.tenant_id == order.tenant_id,
            Conversation.branch_id == order.branch_id,
            func.regexp_replace(Conversation.customer_number, "[^0-9]", "", "g") == digits,
        )
        .order_by(Conversation.last_message_at.desc().nullslast())
    )


async def _language(db: AsyncSession, conv: Conversation | None) -> str:
    if conv is None:
        return "en"
    if conv.language in ("en", "ar"):
        return conv.language
    last_text = await db.scalar(
        select(Message.content)
        .where(Message.conversation_id == conv.id, Message.direction == "in")
        .order_by(Message.created_at.desc())
    )
    return "ar" if last_text and _ARABIC.search(last_text) else "en"


async def send_order_update(db: AsyncSession, payload: dict) -> str:
    """Job handler body. Returns what happened: 'text', 'template' or 'skipped:<reason>'."""
    from app.channels.whatsapp import service as whatsapp  # avoid an import cycle

    order = await db.get(Order, uuid.UUID(payload["order_id"]))
    event = payload["event"]
    if order is None or not order.whatsapp_number:
        return "skipped:no customer number"
    branch = await db.get(Branch, order.branch_id)
    if branch is None or not branch.order_updates_enabled:
        return "skipped:updates switched off"
    if not branch.whatsapp_phone_number_id or not branch.whatsapp_access_token:
        return "skipped:branch has no WhatsApp number"

    tenant = await db.get(Tenant, order.tenant_id)
    driver = None
    if order.assigned_driver_id:
        d = await db.get(User, order.assigned_driver_id)
        driver = (d.full_name or None) if d else None
    conv = await _conversation(db, order)
    language = await _language(db, conv)
    text, phrase = render(event, order, language, business=tenant.name, driver=driver,
                          shorted=payload.get("shorted"))

    last_in = None
    if conv is not None:
        last_in = await db.scalar(
            select(func.max(Message.created_at)).where(Message.conversation_id == conv.id, Message.direction == "in")
        )
    now = datetime.now(timezone.utc)
    to = _digits(order.whatsapp_number)

    if last_in is not None and now - last_in < _WINDOW:
        await whatsapp.send_text(branch, to, text)
        mode, logged = "text", text
    elif branch.whatsapp_update_template:
        name = order.customer_name or ("عميلنا العزيز" if language == "ar" else "there")
        await whatsapp.send_template(branch, to, branch.whatsapp_update_template, language,
                                     [name, order.order_number, phrase])
        mode, logged = "template", text
    else:
        logger.info("order update not sent: outside the 24-hour window and no template set",
                    extra={"ctx_order": order.order_number, "ctx_event": event})
        return "skipped:outside 24-hour window, no template"

    if conv is None:
        conv = Conversation(tenant_id=order.tenant_id, branch_id=order.branch_id, customer_number=to,
                            customer_name=order.customer_name, language=language, status="active")
        db.add(conv)
        await db.flush()
    db.add(Message(tenant_id=order.tenant_id, conversation_id=conv.id, direction="out",
                   sender="system", msg_type="text" if mode == "text" else "template", content=logged))
    conv.last_message_at = now
    await db.commit()
    return mode