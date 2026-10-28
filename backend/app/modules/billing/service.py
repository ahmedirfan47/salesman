"""Subscriptions and invoices.

How billing works:
- Stonic sets up a subscription per business in the admin console: a setup
  fee and a monthly fee, both per branch, plus payment terms.
- Setup fees are invoiced on request, for branches not yet invoiced, so a
  business that opens another branch is billed setup for that branch only.
- Monthly invoices are issued automatically in advance on the subscription's
  `next_invoice_on` date, for the number of active branches on that day.
  If the server was asleep, missed months are caught up the next time it runs.
- Customers pay by bank transfer; Stonic marks the invoice paid.
- An unpaid invoice is "overdue" after its due date. After the grace period
  the account becomes read-only: people can still sign in and look at
  everything, but cannot change anything. The WhatsApp agent keeps serving
  customers throughout. Paying (being marked paid) restores access at once.

All amounts are Decimals rounded to cents. Invoice lines and totals never
change after issue; a wrong invoice is voided and a new one issued.
"""
import calendar
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.billing import INVOICE_NUMBER_SEQ, Invoice, Subscription
from app.db.models.branch import Branch
from app.db.models.tenant import Tenant
from app.db.models.user import User

DEFAULT_SETUP_FEE = Decimal("11000")
DEFAULT_MONTHLY_FEE = Decimal("1050")
DEFAULT_GRACE_DAYS = 14
_CENT = Decimal("0.01")
_MAX_CATCH_UP_MONTHS = 12

SUBSCRIPTION_FIELDS = (
    "status", "currency", "setup_fee_per_branch", "monthly_fee_per_branch", "tax_percent",
    "payment_terms_days", "grace_days", "next_invoice_on", "billing_name", "billing_address",
    "billing_tax_id", "billing_email", "notes",
)


def today() -> date:
    return datetime.now(timezone.utc).date()


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


def fmt_money(currency: str, value) -> str:
    return f"{currency} {money(value):,.2f}"


def add_months(d: date, months: int = 1) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def is_platform_admin(user: User) -> bool:
    return bool(user and user.is_active and user.email and user.email.lower() in settings.platform_admin_emails)


# --- lookups --------------------------------------------------------------------

async def get_tenant(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found")
    return tenant


async def get_subscription(db: AsyncSession, tenant_id: uuid.UUID) -> Subscription | None:
    return await db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))


async def active_branches(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    return int(await db.scalar(
        select(func.count(Branch.id)).where(Branch.tenant_id == tenant_id, Branch.is_active.is_(True))
    ) or 0)


async def get_invoice(db: AsyncSession, invoice_id: uuid.UUID, tenant_id: uuid.UUID | None = None) -> Invoice:
    q = select(Invoice).where(Invoice.id == invoice_id)
    if tenant_id is not None:
        q = q.where(Invoice.tenant_id == tenant_id)
    invoice = await db.scalar(q)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return invoice


async def list_invoices(db: AsyncSession, tenant_id: uuid.UUID) -> list[Invoice]:
    return list(await db.scalars(
        select(Invoice).where(Invoice.tenant_id == tenant_id)
        .order_by(Invoice.issued_on.desc(), Invoice.number.desc())
    ))


# --- subscription ------------------------------------------------------------------

async def upsert_subscription(db: AsyncSession, tenant_id: uuid.UUID, data: dict, *, on: date | None = None) -> Subscription:
    """Create the subscription, or change the fields given. Changes apply to invoices issued from now on."""
    on = on or today()
    tenant = await get_tenant(db, tenant_id)
    sub = await get_subscription(db, tenant_id)
    if sub is None:
        sub = Subscription(
            tenant_id=tenant_id, status="active", currency="USD",
            setup_fee_per_branch=DEFAULT_SETUP_FEE, monthly_fee_per_branch=DEFAULT_MONTHLY_FEE,
            tax_percent=Decimal("0"), payment_terms_days=14, grace_days=DEFAULT_GRACE_DAYS,
            next_invoice_on=on, setup_billed_branches=0, billing_name=tenant.name,
        )
        db.add(sub)
    old_status = sub.status
    for field in SUBSCRIPTION_FIELDS:
        if field in data and data[field] is not None:
            value = data[field]
            if isinstance(value, str):
                value = value.strip() or None
                if value is None and field in ("status", "currency"):
                    continue
            setattr(sub, field, value)
    if sub.currency:
        sub.currency = sub.currency.upper()
    if sub.status not in ("active", "paused", "cancelled"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Status must be active, paused or cancelled")
    if sub.status == "cancelled" and old_status != "cancelled":
        sub.cancelled_on = on
    elif sub.status != "cancelled":
        sub.cancelled_on = None
    await db.commit()
    await db.refresh(sub)
    return sub


# --- issuing ------------------------------------------------------------------------

def _bill_to(tenant: Tenant, sub: Subscription | None) -> dict:
    return {
        "name": (sub.billing_name if sub and sub.billing_name else tenant.name),
        "address": sub.billing_address if sub else None,
        "tax_id": sub.billing_tax_id if sub else None,
        "email": sub.billing_email if sub else None,
    }


def _price_lines(lines: list[dict]) -> tuple[list[dict], Decimal]:
    out, subtotal = [], Decimal("0")
    for line in lines:
        qty = Decimal(str(line["quantity"]))
        unit = money(line["unit_amount"])
        if qty <= 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Each line needs a quantity above zero")
        amount = money(qty * unit)
        subtotal += amount
        out.append({
            "description": str(line["description"]).strip(),
            "quantity": format(qty.normalize(), "f"),
            "unit_amount": str(unit),
            "amount": str(amount),
        })
    if not out:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "An invoice needs at least one line")
    return out, money(subtotal)


async def _issue(
    db: AsyncSession, tenant: Tenant, sub: Subscription | None, *, kind: str, lines: list[dict], issued_on: date,
    due_on: date | None = None, period: tuple[date, date] | None = None, notes: str | None = None,
) -> Invoice:
    priced, subtotal = _price_lines(lines)
    tax_percent = money(sub.tax_percent) if sub else Decimal("0")
    tax = money(subtotal * tax_percent / 100)
    number = await db.scalar(select(INVOICE_NUMBER_SEQ.next_value()))
    invoice = Invoice(
        tenant_id=tenant.id, subscription_id=sub.id if sub else None,
        number=f"{settings.BILLING_INVOICE_PREFIX}-{issued_on.year}-{number:05d}",
        kind=kind, status="open", currency=sub.currency if sub else "USD",
        lines=priced, subtotal=subtotal, tax_percent=tax_percent, tax_amount=tax, total=money(subtotal + tax),
        bill_to=_bill_to(tenant, sub), issued_on=issued_on,
        due_on=due_on or issued_on + timedelta(days=sub.payment_terms_days if sub else 14),
        period_start=period[0] if period else None, period_end=period[1] if period else None, notes=notes,
    )
    db.add(invoice)
    await db.flush()
    return invoice


def _plural(n: int) -> str:
    return f"{n} branch" if n == 1 else f"{n} branches"


async def _issue_monthly(db: AsyncSession, tenant: Tenant, sub: Subscription, issued_on: date) -> Invoice | None:
    """Invoice the period starting on next_invoice_on and move that date on by a month.
    Returns None when that period already has a live invoice (e.g. the date was moved back)."""
    start = sub.next_invoice_on
    end = add_months(start) - timedelta(days=1)
    sub.next_invoice_on = add_months(start)
    already = await db.scalar(select(Invoice.id).where(
        Invoice.subscription_id == sub.id, Invoice.kind == "subscription",
        Invoice.period_start == start, Invoice.status != "void",
    ))
    if already is not None:
        return None
    branches = max(await active_branches(db, tenant.id), 1)
    invoice = await _issue(
        db, tenant, sub, kind="subscription", issued_on=issued_on, period=(start, end),
        lines=[{
            "description": f"Salesman subscription, {_plural(branches)}, {start:%d %b %Y} to {end:%d %b %Y}",
            "quantity": branches, "unit_amount": sub.monthly_fee_per_branch,
        }],
    )
    return invoice


async def issue_due_invoices(db: AsyncSession, *, on: date | None = None, tenant_id: uuid.UUID | None = None) -> int:
    """Issue every monthly invoice that has come due. Safe to run any number of times."""
    on = on or today()
    q = (
        select(Subscription)
        .where(Subscription.status == "active", Subscription.next_invoice_on <= on)
        .with_for_update(skip_locked=True)
    )
    if tenant_id is not None:
        q = q.where(Subscription.tenant_id == tenant_id)
    issued = 0
    for sub in list(await db.scalars(q)):
        tenant = await db.get(Tenant, sub.tenant_id)
        for _ in range(_MAX_CATCH_UP_MONTHS):
            if sub.next_invoice_on > on:
                break
            if await _issue_monthly(db, tenant, sub, on) is not None:
                issued += 1
    await db.commit()
    return issued


async def issue_next_monthly(db: AsyncSession, tenant_id: uuid.UUID, *, on: date | None = None) -> Invoice:
    """Issue the next month's invoice now, before its date."""
    on = on or today()
    tenant = await get_tenant(db, tenant_id)
    sub = await db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id).with_for_update())
    if sub is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Set up the subscription first")
    if sub.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, f"The subscription is {sub.status}")
    invoice = None
    for _ in range(_MAX_CATCH_UP_MONTHS):
        invoice = await _issue_monthly(db, tenant, sub, on)
        if invoice is not None:
            break
    if invoice is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The coming months are already invoiced")
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def unbilled_setup_branches(db: AsyncSession, tenant_id: uuid.UUID, sub: Subscription | None) -> int:
    if sub is None:
        return 0
    return max(await active_branches(db, tenant_id) - sub.setup_billed_branches, 0)


async def issue_setup_invoice(
    db: AsyncSession, tenant_id: uuid.UUID, *, branches: int | None = None, on: date | None = None,
) -> Invoice:
    """Invoice the setup fee for branches not invoiced yet (or an explicit number of branches)."""
    on = on or today()
    tenant = await get_tenant(db, tenant_id)
    sub = await db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id).with_for_update())
    if sub is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Set up the subscription first")
    count = branches if branches is not None else await unbilled_setup_branches(db, tenant_id, sub)
    if count <= 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "The setup fee is already invoiced for every branch")
    invoice = await _issue(
        db, tenant, sub, kind="setup", issued_on=on,
        lines=[{"description": f"Salesman setup and onboarding, {_plural(count)}",
                "quantity": count, "unit_amount": sub.setup_fee_per_branch}],
    )
    sub.setup_billed_branches += count
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def issue_custom_invoice(
    db: AsyncSession, tenant_id: uuid.UUID, lines: list[dict], *, due_on: date | None = None,
    notes: str | None = None, on: date | None = None,
) -> Invoice:
    on = on or today()
    tenant = await get_tenant(db, tenant_id)
    sub = await get_subscription(db, tenant_id)
    if due_on is not None and due_on < on:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The due date can't be in the past")
    invoice = await _issue(db, tenant, sub, kind="other", lines=lines, issued_on=on, due_on=due_on, notes=notes)
    await db.commit()
    await db.refresh(invoice)
    return invoice


# --- payment -----------------------------------------------------------------------

async def mark_paid(db: AsyncSession, invoice_id: uuid.UUID, *, paid_on: date | None = None,
                    reference: str | None = None) -> Invoice:
    invoice = await get_invoice(db, invoice_id)
    if invoice.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, f"This invoice is already {invoice.status}")
    invoice.status = "paid"
    invoice.paid_on = paid_on or today()
    invoice.payment_reference = (reference or "").strip() or None
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def reopen(db: AsyncSession, invoice_id: uuid.UUID) -> Invoice:
    """Undo 'mark paid' (e.g. the transfer bounced or was recorded on the wrong invoice)."""
    invoice = await get_invoice(db, invoice_id)
    if invoice.status != "paid":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a paid invoice can be reopened")
    invoice.status = "open"
    invoice.paid_on = None
    invoice.payment_reference = None
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def void(db: AsyncSession, invoice_id: uuid.UUID, reason: str, *, on: date | None = None) -> Invoice:
    invoice = await get_invoice(db, invoice_id)
    if invoice.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Only an unpaid invoice can be voided. Reopen a paid invoice first.")
    invoice.status = "void"
    invoice.voided_on = on or today()
    invoice.void_reason = reason.strip()
    if invoice.kind == "setup" and invoice.subscription_id:
        sub = await db.get(Subscription, invoice.subscription_id)
        if sub is not None:
            billed = sum(int(Decimal(line["quantity"])) for line in invoice.lines)
            sub.setup_billed_branches = max(sub.setup_billed_branches - billed, 0)
    await db.commit()
    await db.refresh(invoice)
    return invoice


# --- account state ----------------------------------------------------------------

async def account_state(db: AsyncSession, tenant_id: uuid.UUID, *, on: date | None = None) -> dict:
    """'ok' (nothing owed), 'open' (owed, not yet due), 'overdue' (past due, in grace) or 'read_only'."""
    on = on or today()
    open_invoices = list(await db.scalars(
        select(Invoice).where(Invoice.tenant_id == tenant_id, Invoice.status == "open").order_by(Invoice.due_on)
    ))
    sub = await get_subscription(db, tenant_id)
    grace = sub.grace_days if sub else DEFAULT_GRACE_DAYS
    base = {
        "state": "ok", "read_only": False, "open_invoices": len(open_invoices),
        "outstanding": money(sum((i.total for i in open_invoices), Decimal("0"))),
        "overdue": money(sum((i.total for i in open_invoices if i.due_on < on), Decimal("0"))),
        "currency": open_invoices[0].currency if open_invoices else (sub.currency if sub else "USD"),
        "oldest_invoice": None, "oldest_due_on": None, "read_only_from": None,
    }
    if not open_invoices:
        return base
    oldest = open_invoices[0]
    read_only_from = oldest.due_on + timedelta(days=grace + 1)
    state = "read_only" if on >= read_only_from else "overdue" if on > oldest.due_on else "open"
    return {
        **base, "state": state, "read_only": state == "read_only",
        "oldest_invoice": oldest.number, "oldest_due_on": oldest.due_on, "read_only_from": read_only_from,
    }


def state_message(acct: dict, *, admin: bool) -> str | None:
    state = acct["state"]
    if state == "read_only":
        if not admin:
            return "This account is read-only until an overdue invoice is paid. Please contact your administrator."
        return (f"This account is read-only because invoice {acct['oldest_invoice']} was due on "
                f"{acct['oldest_due_on']:%d %b %Y}. Pay the overdue {fmt_money(acct['currency'], acct['overdue'])} by bank "
                "transfer (see Billing & Plan) and access is restored as soon as Stonic confirms the payment.")
    if state == "overdue" and admin:
        return (f"Invoice {acct['oldest_invoice']} was due on {acct['oldest_due_on']:%d %b %Y}. "
                f"The account becomes read-only on {acct['read_only_from']:%d %b %Y} unless it is paid.")
    return None


READ_ONLY_DETAIL = ("This account is read-only because an invoice is overdue. You can still view everything; "
                    "changes are switched off until the invoice is paid.")


async def is_read_only(db: AsyncSession, tenant_id: uuid.UUID, *, on: date | None = None) -> bool:
    """Cheap check used on every write request."""
    on = on or today()
    row = (await db.execute(
        select(func.min(Invoice.due_on), func.max(Subscription.grace_days))
        .select_from(Invoice)
        .outerjoin(Subscription, Subscription.tenant_id == Invoice.tenant_id)
        .where(Invoice.tenant_id == tenant_id, Invoice.status == "open")
    )).one()
    oldest_due, grace = row
    if oldest_due is None:
        return False
    grace = DEFAULT_GRACE_DAYS if grace is None else grace
    return on >= oldest_due + timedelta(days=grace + 1)


# --- console ------------------------------------------------------------------------

async def tenant_overview(db: AsyncSession, tenant: Tenant, *, on: date | None = None) -> dict:
    sub = await get_subscription(db, tenant.id)
    users = int(await db.scalar(select(func.count(User.id)).where(User.tenant_id == tenant.id)) or 0)
    return {
        "id": tenant.id, "name": tenant.name, "slug": tenant.slug, "created_at": tenant.created_at,
        "active_branches": await active_branches(db, tenant.id), "users": users,
        "subscription": sub, "unbilled_setup_branches": await unbilled_setup_branches(db, tenant.id, sub),
        "account": await account_state(db, tenant.id, on=on),
    }


async def list_tenants(db: AsyncSession, *, on: date | None = None) -> list[dict]:
    await issue_due_invoices(db, on=on)
    tenants = list(await db.scalars(select(Tenant).order_by(Tenant.name)))
    return [await tenant_overview(db, t, on=on) for t in tenants]