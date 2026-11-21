"""Payment reminders on WhatsApp.

A business switches reminders on (Accounts > Settings). Then, for every unpaid
invoice of a customer with a WhatsApp number:

- "due_soon": one reminder `reminder_days_before_due` days before the due date
  (0 = none);
- "overdue_1", "overdue_2", ...: the day after the due date, then every
  `reminder_repeat_days` days, at most `reminder_max_overdue` times.

Each (invoice, stage) is sent at most once (a CollectionReminder row with a
unique index) and only between 09:00 and 20:59 business time. Customers on
hold are reminded too: they still owe the money.

WhatsApp allows free text only within 24 hours of the customer's last
message. Outside it, the business's approved template is used
(`reminder_template`, parameters: name, invoice number, amount due, due
date); without one the reminder is recorded as skipped, never failed.
The customer can reply and the AI agent answers with their balance, a
statement or an invoice copy, which it already knows how to do.
"""
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountSettings, SalesInvoice
from app.db.models.branch import Branch
from app.db.models.collection_reminder import CollectionReminder
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.message import Message
from app.db.models.tenant import Tenant
from app.jobs.queue import WHATSAPP_COLLECTION_REMINDER, enqueue
from app.modules.notifications.service import _language, _money

logger = logging.getLogger("salesman.collections")

SEND_FROM_HOUR, SEND_UNTIL_HOUR = 9, 21  # business local time
_WINDOW = timedelta(hours=23, minutes=50)

# Suggested template to submit in Meta (category: Utility):
TEMPLATE_HINT = {
    "en": "Hello {{1}}, a reminder that invoice {{2}} has {{3}} due on {{4}}. "
          "Reply to this message for a statement or if you have already paid.",
    "ar": "مرحباً {{1}}، تذكير بأن الفاتورة {{2}} عليها مبلغ {{3}} مستحق بتاريخ {{4}}. "
          "رد على هذه الرسالة لطلب كشف حساب أو إذا تم السداد.",
}


def _tz(tenant: Tenant | None):
    try:
        return ZoneInfo(tenant.timezone) if tenant and tenant.timezone else timezone.utc
    except ZoneInfoNotFoundError:
        return timezone.utc


def stage_for(due: date, today: date, s: AccountSettings) -> str | None:
    """Which reminder (if any) an unpaid invoice due on `due` should get today."""
    days_to_due = (due - today).days
    if 0 < days_to_due <= s.reminder_days_before_due:
        return "due_soon"
    days_overdue = (today - due).days
    if days_overdue >= 1 and s.reminder_max_overdue > 0:
        k = 1 + (days_overdue - 1) // max(s.reminder_repeat_days, 1)
        if k <= s.reminder_max_overdue:
            return f"overdue_{k}"
    return None


async def queue_due_reminders(
    db: AsyncSession, tenant_id: uuid.UUID, *, now: datetime | None = None, ignore_hours: bool = False,
) -> int:
    """Queue every reminder due today for one business. Safe to run any number of times."""
    s = await db.scalar(select(AccountSettings).where(AccountSettings.tenant_id == tenant_id))
    if s is None or not s.reminders_enabled:
        return 0
    tenant = await db.get(Tenant, tenant_id)
    local = (now or datetime.now(timezone.utc)).astimezone(_tz(tenant))
    if not ignore_hours and not (SEND_FROM_HOUR <= local.hour < SEND_UNTIL_HOUR):
        return 0
    today = local.date()

    horizon = today + timedelta(days=s.reminder_days_before_due)
    rows = (await db.execute(
        select(SalesInvoice, Customer)
        .join(Customer, Customer.id == SalesInvoice.customer_id)
        .where(
            SalesInvoice.tenant_id == tenant_id,
            SalesInvoice.kind.in_(("invoice", "opening_balance")),
            SalesInvoice.status.in_(("open", "partially_paid")),
            SalesInvoice.due_date <= horizon,
            Customer.whatsapp_number.is_not(None),
            Customer.is_active.is_(True),
        )
    )).all()
    if not rows:
        return 0
    already = {
        (r.invoice_id, r.stage) for r in await db.scalars(
            select(CollectionReminder).where(
                CollectionReminder.tenant_id == tenant_id,
                CollectionReminder.invoice_id.in_([inv.id for inv, _ in rows]),
            )
        )
    }
    queued = 0
    for inv, customer in rows:
        if inv.balance_due <= 0:
            continue
        stage = stage_for(inv.due_date, today, s)
        if stage is None or (inv.id, stage) in already:
            continue
        reminder = CollectionReminder(
            tenant_id=tenant_id, invoice_id=inv.id, customer_id=customer.id, stage=stage, status="queued",
        )
        db.add(reminder)
        await db.flush()
        await enqueue(
            db, WHATSAPP_COLLECTION_REMINDER, {"reminder_id": str(reminder.id)},
            tenant_id=tenant_id, dedupe_key=f"collect:{inv.id}:{stage}", max_attempts=4, commit=False,
        )
        queued += 1
    await db.commit()
    return queued


async def queue_all(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Worker sweep: queue due reminders for every business that has them switched on."""
    tenant_ids = list(await db.scalars(
        select(AccountSettings.tenant_id).where(AccountSettings.reminders_enabled.is_(True))
    ))
    total = 0
    for tid in tenant_ids:
        try:
            total += await queue_due_reminders(db, tid, now=now)
        except Exception:  # noqa: BLE001 -- one business's bad data must not stop the others
            await db.rollback()
            logger.exception("collection reminders failed", extra={"ctx_tenant_id": str(tid)})
    return total


def render(stage: str, language: str, *, name: str, business: str, number: str, amount: str,
           due: date, days_overdue: int) -> str:
    due_txt = due.isoformat()
    if language == "ar":
        if stage == "due_soon":
            return (f"مرحباً {name}، تذكير ودي من {business}: الفاتورة {number} بمبلغ {amount} "
                    f"تستحق بتاريخ {due_txt}. للاستفسار أو لطلب كشف حساب، رد على هذه الرسالة.")
        return (f"مرحباً {name}، الفاتورة {number} بمبلغ {amount} متأخرة {days_overdue} يوم "
                f"(تاريخ الاستحقاق {due_txt}). نرجو السداد في أقرب وقت. إذا تم السداد، تجاهل هذه الرسالة "
                f"أو أرسل لنا إشعار التحويل.")
    if stage == "due_soon":
        return (f"Hello {name}, a friendly reminder from {business}: invoice {number} for {amount} "
                f"is due on {due_txt}. Reply here for a statement or any question.")
    return (f"Hello {name}, invoice {number} for {amount} is {days_overdue} day"
            f"{'' if days_overdue == 1 else 's'} overdue (due {due_txt}). Please arrange payment. "
            f"If you have already paid, reply with the transfer receipt and we will update your account.")


async def send_reminder(db: AsyncSession, reminder_id: uuid.UUID) -> str:
    """Job handler body. Returns 'sent_text', 'sent_template' or 'skipped:<reason>'."""
    from app.channels.whatsapp import service as whatsapp  # avoid an import cycle

    r = await db.get(CollectionReminder, reminder_id)
    if r is None or r.status != "queued":
        return "skipped:already handled"
    inv = await db.get(SalesInvoice, r.invoice_id)
    customer = await db.get(Customer, r.customer_id) if r.customer_id else None

    async def skip(reason: str) -> str:
        r.status, r.detail = "skipped", reason[:255]
        await db.commit()
        return f"skipped:{reason}"

    if inv is None or customer is None or not customer.whatsapp_number:
        return await skip("no invoice or customer number")
    if inv.balance_due <= 0:
        return await skip("paid before the reminder went out")
    branch = await db.get(Branch, inv.branch_id) if inv.branch_id else None
    if branch is None or not branch.whatsapp_phone_number_id or not branch.whatsapp_access_token:
        return await skip("branch has no WhatsApp number")
    s = await db.scalar(select(AccountSettings).where(AccountSettings.tenant_id == r.tenant_id))
    if s is None or not s.reminders_enabled:
        return await skip("reminders switched off")

    tenant = await db.get(Tenant, r.tenant_id)
    digits = re.sub(r"\D", "", customer.whatsapp_number)
    conv = await db.scalar(
        select(Conversation)
        .where(
            Conversation.tenant_id == r.tenant_id, Conversation.branch_id == branch.id,
            func.regexp_replace(Conversation.customer_number, "[^0-9]", "", "g") == digits,
        )
        .order_by(Conversation.last_message_at.desc().nullslast())
    )
    language = await _language(db, conv)
    today = datetime.now(_tz(tenant)).date()
    amount = _money(inv.balance_due, inv.currency, language)
    name = customer.name or ("عميلنا العزيز" if language == "ar" else "there")
    text = render(r.stage, language, name=name, business=tenant.name, number=inv.number, amount=amount,
                  due=inv.due_date, days_overdue=max((today - inv.due_date).days, 0))

    last_in = None
    if conv is not None:
        last_in = await db.scalar(
            select(func.max(Message.created_at)).where(Message.conversation_id == conv.id, Message.direction == "in")
        )
    now = datetime.now(timezone.utc)
    if last_in is not None and now - last_in < _WINDOW:
        await whatsapp.send_text(branch, digits, text)
        mode = "sent_text"
    elif s.reminder_template:
        await whatsapp.send_template(branch, digits, s.reminder_template, language,
                                     [name, inv.number, amount, inv.due_date.isoformat()])
        mode = "sent_template"
    else:
        return await skip("outside the 24-hour window and no reminder template set")

    if conv is None:
        conv = Conversation(tenant_id=r.tenant_id, branch_id=branch.id, customer_number=digits,
                            customer_name=customer.name, language=language, status="active")
        db.add(conv)
        await db.flush()
    db.add(Message(tenant_id=r.tenant_id, conversation_id=conv.id, direction="out", sender="system",
                   msg_type="text" if mode == "sent_text" else "template", content=text))
    conv.last_message_at = now
    r.status, r.sent_at, r.detail = mode, now, None
    await db.commit()
    return mode


async def list_reminders(db: AsyncSession, tenant_id: uuid.UUID, *, limit: int = 100) -> list[dict]:
    rows = (await db.execute(
        select(CollectionReminder, SalesInvoice.number, Customer.name)
        .join(SalesInvoice, SalesInvoice.id == CollectionReminder.invoice_id)
        .outerjoin(Customer, Customer.id == CollectionReminder.customer_id)
        .where(CollectionReminder.tenant_id == tenant_id)
        .order_by(CollectionReminder.created_at.desc())
        .limit(limit)
    )).all()
    return [
        {
            "id": r.id, "invoice_number": number, "customer_name": cname, "stage": r.stage,
            "status": r.status, "detail": r.detail, "created_at": r.created_at, "sent_at": r.sent_at,
        }
        for r, number, cname in rows
    ]
