"""Monthly AI accuracy report, per customer.

For every order the WhatsApp AI placed in the month (orders.source = 'ai'):
- confirmed: the AI was sure and the order went straight through;
- approved: held for a check ('ai_review') and approved as it was;
- corrected: held, and the team changed products or quantities before approving;
- rejected: held and rejected by the team;
- waiting: held and not decided yet (left out of the rates).
Orders held only for stock or credit count as confirmed: that hold is about
the business, not about what the AI understood.

Order accuracy = (confirmed + approved) / decided orders.
Line accuracy  = 1 - lines changed in corrections / lines in decided orders
                 (a rejected order counts all its lines as wrong).
Time saved is an estimate: orders the team did not have to fix, times
MINUTES_PER_ORDER minutes of typing each, shown as an estimate.
"""
import calendar
import csv
import io
import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.customer import Customer
from app.db.models.escalation import Escalation
from app.db.models.order import Order
from app.db.models.order_item import OrderItem
from app.db.models.tenant import Tenant

MINUTES_PER_ORDER = 4


def month_bounds(month: date, tz_name: str | None) -> tuple[datetime, datetime]:
    try:
        tz = ZoneInfo(tz_name) if tz_name else timezone.utc
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    start = datetime(month.year, month.month, 1, tzinfo=tz)
    nxt = datetime(month.year + (month.month == 12), month.month % 12 + 1, 1, tzinfo=tz)
    return start.astimezone(timezone.utc), nxt.astimezone(timezone.utc)


def _rate(good: int, total: int) -> float | None:
    return round(good / total * 100, 1) if total else None


def _blank(key: str, name: str, customer_id) -> dict:
    return {"key": key, "customer_id": customer_id, "customer": name, "orders": 0, "confirmed": 0, "approved": 0,
            "corrected": 0, "rejected": 0, "waiting": 0, "lines": 0, "lines_changed": 0}


def _finish(row: dict) -> dict:
    decided = row["confirmed"] + row["approved"] + row["corrected"] + row["rejected"]
    row["decided"] = decided
    row["order_accuracy"] = _rate(row["confirmed"] + row["approved"], decided)
    row["line_accuracy"] = _rate(row["lines"] - row["lines_changed"], row["lines"])
    row["minutes_saved"] = (row["confirmed"] + row["approved"]) * MINUTES_PER_ORDER
    return row


async def monthly(db: AsyncSession, tenant_id: uuid.UUID, month: date, scope: uuid.UUID | None = None) -> dict:
    tenant = await db.get(Tenant, tenant_id)
    start, end = month_bounds(month, tenant.timezone if tenant else None)
    q = select(Order).where(Order.tenant_id == tenant_id, Order.source == "ai",
                            Order.created_at >= start, Order.created_at < end)
    if scope is not None:
        q = q.where(Order.branch_id == scope)
    orders = list(await db.scalars(q.order_by(Order.created_at)))
    ids = [o.id for o in orders]
    escalations = {e.order_id: e for e in await db.scalars(select(Escalation).where(
        Escalation.order_id.in_(ids), Escalation.reason_type == "ai_review"))} if ids else {}
    line_counts = dict((await db.execute(
        select(OrderItem.order_id, func.count()).where(OrderItem.order_id.in_(ids), OrderItem.is_free.is_(False))
        .group_by(OrderItem.order_id)
    )).all()) if ids else {}
    customers = {c.id: c for c in await db.scalars(select(Customer).where(
        Customer.id.in_({o.customer_id for o in orders if o.customer_id})))} if orders else {}

    rows: dict[str, dict] = {}
    total = _blank("all", "All customers", None)
    for o in orders:
        c = customers.get(o.customer_id)
        key = str(o.customer_id) if o.customer_id else f"wa:{o.whatsapp_number or 'unknown'}"
        name = (c.company or c.name) if c else (o.customer_company or o.customer_name or o.whatsapp_number or "Unknown")
        row = rows.setdefault(key, _blank(key, name, o.customer_id))
        esc = escalations.get(o.id)
        ctx = (esc.context or {}) if esc else {}
        lines = int(ctx.get("lines_before") or line_counts.get(o.id, 0))
        if esc is None:
            outcome, changed = "confirmed", 0
        elif esc.status == "open":
            outcome, changed = "waiting", 0
        elif esc.resolution == "rejected":
            outcome, changed = "rejected", lines
        elif ctx.get("corrected"):
            outcome, changed = "corrected", min(int(ctx.get("lines_changed") or 1), max(lines, 1))
        else:
            outcome, changed = "approved", 0
        for r in (row, total):
            r["orders"] += 1
            r[outcome] += 1
            if outcome != "waiting":
                r["lines"] += lines
                r["lines_changed"] += changed
    customers_out = sorted((_finish(r) for r in rows.values()), key=lambda r: (-r["orders"], r["customer"]))
    last_day = calendar.monthrange(month.year, month.month)[1]
    return {
        "month": month.strftime("%Y-%m"),
        "period": {"from": date(month.year, month.month, 1), "to": date(month.year, month.month, last_day)},
        "totals": _finish(total),
        "customers": customers_out,
        "minutes_per_order": MINUTES_PER_ORDER,
    }


def to_csv(report: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Month", "Customer", "AI orders", "Confirmed", "Approved as is", "Corrected", "Rejected", "Waiting",
                "Order accuracy %", "Lines", "Lines changed", "Line accuracy %", "Minutes saved (estimate)"])
    for r in [*report["customers"], report["totals"]]:
        w.writerow([report["month"], r["customer"], r["orders"], r["confirmed"], r["approved"], r["corrected"],
                    r["rejected"], r["waiting"], "" if r["order_accuracy"] is None else r["order_accuracy"], r["lines"],
                    r["lines_changed"], "" if r["line_accuracy"] is None else r["line_accuracy"], r["minutes_saved"]])
    return out.getvalue()
