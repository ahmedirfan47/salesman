"""The reorder agent: message customers who are late for their usual order.

Every customer reorders on a rhythm (every 4 days, every 2 weeks). For a
customer with a WhatsApp number and at least `reorder_min_orders` orders, the
typical gap is the median number of days between their recent orders. When
`reorder_factor` x that gap has passed since their last order and they
haven't ordered again, they get one WhatsApp message offering their last
order again ("Reply YES to send the same order"). The AI agent already knows
"same as last time", so a reply turns into an order through the normal,
checked flow -- nothing is ordered without the customer confirming.

Rules that keep it polite:
- at most one message per customer per last order (a customer who doesn't
  answer is not chased again until they order);
- only between 09:00 and 20:59 business time;
- outside WhatsApp's 24-hour window only the business's approved template
  is used (`reorder_template`, parameters: name, items); without one the
  message is recorded as skipped;
- customers on hold, inactive or without a number are left out.

A nudge counts as converted when the customer orders within ATTRIBUTION_DAYS
of it. The dashboard shows sent, converted and the value of those orders.
"""
import logging
import math
import re
import statistics
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_settings import AgentSettings
from app.db.models.branch import Branch
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.message import Message
from app.db.models.order import Order
from app.db.models.order_item import OrderItem
from app.db.models.reorder import ReorderNudge
from app.db.models.tenant import Tenant
from app.jobs.queue import WHATSAPP_REORDER_NUDGE, enqueue
from app.modules.collections.service import SEND_FROM_HOUR, SEND_UNTIL_HOUR, _tz
from app.modules.notifications.service import _language

logger = logging.getLogger("salesman.reorder")

LIVE = ("confirmed", "preparing", "dispatched", "delivered", "completed")
HISTORY = 10              # orders looked at for the rhythm
ATTRIBUTION_DAYS = 7
_WINDOW = timedelta(hours=23, minutes=50)

TEMPLATE_HINT = {
    "en": "Hello {{1}}, it's about time for your usual order: {{2}}. Reply YES to order the same again, "
          "or tell us what to change.",
    "ar": "مرحباً {{1}}، حان وقت طلبك المعتاد: {{2}}. رد بـ نعم لتكرار نفس الطلب، أو أخبرنا بما تريد تغييره.",
}


def typical_gap(days: list[date]) -> int | None:
    """Median days between consecutive order days (several orders on one day count once)."""
    ordered = sorted(set(days))
    gaps = [(b - a).days for a, b in zip(ordered, ordered[1:])]
    if not gaps:
        return None
    return max(int(round(statistics.median(gaps))), 1)


def _items_text(items: list[dict], language: str) -> str:
    parts = [f"{i['quantity']} x {i['name_ar'] if language == 'ar' and i.get('name_ar') else i['name']}" for i in items]
    text = "، ".join(parts) if language == "ar" else ", ".join(parts)
    return text[:600]


def render(language: str, *, name: str, business: str, items: list[dict]) -> str:
    listing = _items_text(items, language)
    if language == "ar":
        return (f"مرحباً {name}، معك {business}. حان وقت طلبك المعتاد: {listing}. "
                "رد بـ «نعم» لنرسل نفس الطلب، أو أخبرنا بما تريد تغييره.")
    return (f"Hello {name}, {business} here. It's about time for your usual order: {listing}. "
            "Reply YES to order the same again, or tell us what to change.")


async def get_settings(db: AsyncSession, tenant_id: uuid.UUID) -> AgentSettings:
    from app.modules.orders.review import get_settings as agent_settings
    return await agent_settings(db, tenant_id)


async def candidates(db: AsyncSession, tenant_id: uuid.UUID, today: date, *, horizon_days: int = 0) -> list[dict]:
    """Customers due for a nudge today (or within `horizon_days`, for the dashboard)."""
    s = await get_settings(db, tenant_id)
    tenant = await db.get(Tenant, tenant_id)
    tz = _tz(tenant)
    rows = (await db.execute(
        select(Order.customer_id, Order.id, Order.created_at)
        .join(Customer, Customer.id == Order.customer_id)
        .where(Order.tenant_id == tenant_id, Order.status.in_(LIVE), Customer.is_active.is_(True),
               Customer.whatsapp_number.is_not(None))
        .order_by(Order.customer_id, Order.created_at.desc())
    )).all()
    history: dict[uuid.UUID, list] = {}
    for cid, oid, created in rows:
        if len(history.setdefault(cid, [])) < HISTORY:
            history[cid].append((oid, created))
    if not history:
        return []
    nudged = {last for last, in (await db.execute(
        select(ReorderNudge.last_order_id).where(ReorderNudge.tenant_id == tenant_id)
    )).all()}
    customers = {c.id: c for c in await db.scalars(select(Customer).where(Customer.id.in_(list(history))))}
    out = []
    for cid, orders in history.items():
        if len(orders) < s.reorder_min_orders:
            continue
        c = customers[cid]
        if getattr(c, "on_hold", False):
            continue
        last_id, last_at = orders[0]
        if last_id in nudged:
            continue
        gap = typical_gap([o[1].astimezone(tz).date() for o in orders])
        if gap is None:
            continue
        last_day = last_at.astimezone(tz).date()
        due = last_day + timedelta(days=math.ceil(gap * float(s.reorder_factor)))
        if due <= today + timedelta(days=horizon_days):
            out.append({"customer": c, "last_order_id": last_id, "last_order_on": last_day, "typical_days": gap,
                        "due_on": due, "days_late": (today - due).days})
    out.sort(key=lambda x: x["due_on"])
    return out


async def _suggested(db: AsyncSession, order_id: uuid.UUID) -> list[dict]:
    from app.db.models.product import Product

    rows = (await db.execute(
        select(OrderItem.sku, OrderItem.product_name, OrderItem.quantity, Product.name_ar)
        .join(Product, Product.id == OrderItem.product_id)
        .where(OrderItem.order_id == order_id, OrderItem.is_free.is_(False))
        .order_by(OrderItem.line_total.desc())
    )).all()
    return [{"sku": sku, "name": name, "name_ar": ar, "quantity": qty} for sku, name, qty, ar in rows]


async def queue_due(db: AsyncSession, tenant_id: uuid.UUID, *, now: datetime | None = None,
                    ignore_hours: bool = False) -> int:
    s = await get_settings(db, tenant_id)
    if not s.reorder_enabled:
        return 0
    tenant = await db.get(Tenant, tenant_id)
    local = (now or datetime.now(timezone.utc)).astimezone(_tz(tenant))
    if not ignore_hours and not (SEND_FROM_HOUR <= local.hour < SEND_UNTIL_HOUR):
        return 0
    queued = 0
    for cand in await candidates(db, tenant_id, local.date()):
        nudge = ReorderNudge(
            tenant_id=tenant_id, customer_id=cand["customer"].id, last_order_id=cand["last_order_id"],
            status="queued", due_on=cand["due_on"], typical_days=cand["typical_days"],
            suggested=await _suggested(db, cand["last_order_id"]),
        )
        db.add(nudge)
        await db.flush()
        await enqueue(db, WHATSAPP_REORDER_NUDGE, {"nudge_id": str(nudge.id)}, tenant_id=tenant_id,
                      dedupe_key=f"reorder:{cand['last_order_id']}", max_attempts=4, commit=False)
        queued += 1
    await db.commit()
    return queued


async def queue_all(db: AsyncSession, *, now: datetime | None = None) -> int:
    total = 0
    for tid in list(await db.scalars(select(AgentSettings.tenant_id).where(AgentSettings.reorder_enabled.is_(True)))):
        try:
            total += await queue_due(db, tid, now=now)
        except Exception:  # noqa: BLE001 -- one business's bad data must not stop the others
            await db.rollback()
            logger.exception("reorder nudges failed", extra={"ctx_tenant_id": str(tid)})
    return total


async def send_nudge(db: AsyncSession, nudge_id: uuid.UUID) -> str:
    """Job handler body: 'sent_text', 'sent_template' or 'skipped:<reason>'."""
    from app.channels.whatsapp import service as whatsapp  # avoid an import cycle

    n = await db.get(ReorderNudge, nudge_id)
    if n is None or n.status != "queued":
        return "skipped:already handled"

    async def skip(reason: str) -> str:
        n.status, n.error = "skipped", reason[:500]
        await db.commit()
        return f"skipped:{reason}"

    s = await get_settings(db, n.tenant_id)
    if not s.reorder_enabled:
        return await skip("reorder messages switched off")
    customer = await db.get(Customer, n.customer_id)
    if customer is None or not customer.whatsapp_number or not customer.is_active:
        return await skip("no active customer with a WhatsApp number")
    newer = await db.scalar(select(func.count()).select_from(Order).where(
        Order.tenant_id == n.tenant_id, Order.customer_id == customer.id,
        Order.created_at > (await db.get(Order, n.last_order_id)).created_at,
    ))
    if newer:
        return await skip("the customer ordered before the message went out")
    if not n.suggested:
        return await skip("the last order had no items to repeat")
    branch = await db.get(Branch, customer.branch_id) if customer.branch_id else None
    if branch is None or not branch.whatsapp_phone_number_id or not branch.whatsapp_access_token:
        return await skip("branch has no WhatsApp number")

    tenant = await db.get(Tenant, n.tenant_id)
    digits = re.sub(r"\D", "", customer.whatsapp_number)
    conv = await db.scalar(
        select(Conversation).where(
            Conversation.tenant_id == n.tenant_id, Conversation.branch_id == branch.id,
            func.regexp_replace(Conversation.customer_number, "[^0-9]", "", "g") == digits,
        ).order_by(Conversation.last_message_at.desc().nullslast())
    )
    language = await _language(db, conv)
    name = customer.name or ("عميلنا العزيز" if language == "ar" else "there")
    text = render(language, name=name, business=tenant.name, items=n.suggested)
    last_in = await db.scalar(select(func.max(Message.created_at)).where(
        Message.conversation_id == conv.id, Message.direction == "in")) if conv is not None else None
    now = datetime.now(timezone.utc)
    if last_in is not None and now - last_in < _WINDOW:
        await whatsapp.send_text(branch, digits, text)
        mode = "sent_text"
    elif s.reorder_template:
        await whatsapp.send_template(branch, digits, s.reorder_template, language,
                                     [name, _items_text(n.suggested, language)])
        mode = "sent_template"
    else:
        return await skip("outside the 24-hour window and no reorder template set")
    if conv is None:
        conv = Conversation(tenant_id=n.tenant_id, branch_id=branch.id, customer_number=digits,
                            customer_name=customer.name, language=language, status="active")
        db.add(conv)
        await db.flush()
    db.add(Message(tenant_id=n.tenant_id, conversation_id=conv.id, direction="out", sender="system",
                   msg_type="text" if mode == "sent_text" else "template", content=text))
    conv.last_message_at = now
    n.status, n.sent_at, n.message, n.error = "sent", now, text, None
    await db.commit()
    return mode


async def _attribute(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Link sent nudges to the first order the customer placed within ATTRIBUTION_DAYS."""
    open_ = list(await db.scalars(select(ReorderNudge).where(
        ReorderNudge.tenant_id == tenant_id, ReorderNudge.status == "sent", ReorderNudge.converted_order_id.is_(None),
        ReorderNudge.sent_at >= datetime.now(timezone.utc) - timedelta(days=ATTRIBUTION_DAYS + 30),
    )))
    changed = False
    for n in open_:
        order = await db.scalar(select(Order).where(
            Order.tenant_id == tenant_id, Order.customer_id == n.customer_id, Order.created_at > n.sent_at,
            Order.created_at <= n.sent_at + timedelta(days=ATTRIBUTION_DAYS),
            Order.status.notin_(("cancelled", "failed")),
        ).order_by(Order.created_at).limit(1))
        if order is not None:
            n.converted_order_id, n.converted_at, changed = order.id, order.created_at, True
    if changed:
        await db.commit()


async def overview(db: AsyncSession, tenant_id: uuid.UUID, *, limit: int = 100) -> dict:
    await _attribute(db, tenant_id)
    s = await get_settings(db, tenant_id)
    tenant = await db.get(Tenant, tenant_id)
    today = datetime.now(_tz(tenant)).date()
    rows = (await db.execute(
        select(ReorderNudge, Customer.name, Customer.company, Order.order_number, Order.total_amount, Order.currency)
        .join(Customer, Customer.id == ReorderNudge.customer_id)
        .outerjoin(Order, Order.id == ReorderNudge.converted_order_id)
        .where(ReorderNudge.tenant_id == tenant_id).order_by(ReorderNudge.created_at.desc()).limit(limit)
    )).all()
    nudges = [{
        "id": n.id, "customer_id": n.customer_id, "customer": company or name, "status": n.status,
        "due_on": n.due_on, "typical_days": n.typical_days, "suggested": n.suggested, "error": n.error,
        "sent_at": n.sent_at, "created_at": n.created_at, "converted_order": number,
        "converted_amount": amount, "currency": currency,
    } for n, name, company, number, amount, currency in rows]
    sent = await db.scalar(select(func.count()).select_from(ReorderNudge).where(
        ReorderNudge.tenant_id == tenant_id, ReorderNudge.status == "sent")) or 0
    conv = (await db.execute(
        select(func.count(), func.coalesce(func.sum(Order.total_amount), 0))
        .select_from(ReorderNudge).join(Order, Order.id == ReorderNudge.converted_order_id)
        .where(ReorderNudge.tenant_id == tenant_id)
    )).one()
    upcoming = [{
        "customer_id": c["customer"].id, "customer": c["customer"].company or c["customer"].name,
        "last_order_on": c["last_order_on"], "typical_days": c["typical_days"], "due_on": c["due_on"],
        "days_late": c["days_late"],
    } for c in await candidates(db, tenant_id, today, horizon_days=7)]
    return {
        "enabled": s.reorder_enabled, "factor": s.reorder_factor, "min_orders": s.reorder_min_orders,
        "template": s.reorder_template, "template_hint": TEMPLATE_HINT,
        "stats": {"sent": sent, "converted": conv[0], "conversion_rate": round(conv[0] / sent * 100, 1) if sent else None,
                  "converted_value": Decimal(str(conv[1])).quantize(Decimal("0.01"))},
        "upcoming": upcoming, "nudges": nudges,
    }
