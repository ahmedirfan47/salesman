"""What the Stonic Console shows and does across every business on the platform.

Read-only queries (analytics, businesses, people, system health) and the few
changes Stonic makes on a business's behalf (suspend, switch a person off,
set a password, end sessions, retry or discard a background job). Every
change is written to the audit log in the same transaction.
"""
import platform as host
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import and_, distinct, func, literal_column, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.enums import UserRole
from app.core.security import hash_password
from app.db.models.accounts import SalesInvoice
from app.db.models.branch import Branch
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.integration import IntegrationConnection, IntegrationEvent
from app.db.models.job import Job
from app.db.models.message import Message
from app.db.models.order import Order
from app.db.models.platform import AdminAuditLog, LoginEvent, UserActivity
from app.db.models.product import Product
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.models.zatca import ZatcaDocument, ZatcaUnit
from app.modules.analytics.service import REVENUE_STATUSES
from app.modules.platform.access import is_platform_admin
from app.modules.platform.activity import audit

PERIODS = (7, 30, 90)
ONLINE_WINDOW = timedelta(minutes=10)
STARTED_AT = datetime.now(timezone.utc)
_STARTED_MONO = time.monotonic()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day(column):
    """The UTC calendar day of a timestamp column."""
    return func.date(func.timezone(literal_column("'UTC'"), column))


def _count_by(rows) -> dict:
    return {k: int(v or 0) for k, v in rows}


# ---- overview ---------------------------------------------------------------------------------

async def overview(db: AsyncSession, days: int) -> dict:
    if days not in PERIODS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose 7, 30 or 90 days")
    now = _now()
    today = now.date()
    start = today - timedelta(days=days - 1)
    start_at = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)

    async def scalar(q) -> int:
        return int(await db.scalar(q) or 0)

    totals = {
        "businesses": await scalar(select(func.count(Tenant.id))),
        "businesses_suspended": await scalar(select(func.count(Tenant.id)).where(Tenant.suspended_at.is_not(None))),
        "people": await scalar(select(func.count(User.id)).where(User.is_active.is_(True))),
        "branches": await scalar(select(func.count(Branch.id)).where(Branch.is_active.is_(True))),
        "customers": await scalar(select(func.count(Customer.id))),
        "products": await scalar(select(func.count(Product.id))),
        "orders": await scalar(select(func.count(Order.id))),
        "conversations": await scalar(select(func.count(Conversation.id))),
        "online_now": await scalar(select(func.count(User.id)).where(User.last_seen_at >= now - ONLINE_WINDOW)),
    }

    # people active per day and client
    per_client = await db.execute(
        select(UserActivity.day, UserActivity.client, func.count(distinct(UserActivity.user_id)))
        .where(UserActivity.day >= start).group_by(UserActivity.day, UserActivity.client)
    )
    any_client = await db.execute(
        select(UserActivity.day, func.count(distinct(UserActivity.user_id)))
        .where(UserActivity.day >= start).group_by(UserActivity.day)
    )
    sign_ins = await db.execute(
        select(_day(LoginEvent.created_at), func.count(LoginEvent.id))
        .where(LoginEvent.created_at >= start_at, LoginEvent.success.is_(True)).group_by(_day(LoginEvent.created_at))
    )
    orders = await db.execute(
        select(_day(Order.created_at), func.count(Order.id))
        .where(Order.created_at >= start_at).group_by(_day(Order.created_at))
    )
    messages = await db.execute(
        select(_day(Message.created_at), func.count(Message.id))
        .where(Message.created_at >= start_at).group_by(_day(Message.created_at))
    )
    new_businesses = await db.execute(
        select(_day(Tenant.created_at), func.count(Tenant.id))
        .where(Tenant.created_at >= start_at).group_by(_day(Tenant.created_at))
    )

    web: dict = {}
    mobile: dict = {}
    for day_, client, n in per_client:
        if client == "web":
            web[day_] = int(n)
        elif client == "mobile":
            mobile[day_] = int(n)
    active = _count_by(any_client)
    sign_in_by_day, orders_by_day = _count_by(sign_ins), _count_by(orders)
    messages_by_day, businesses_by_day = _count_by(messages), _count_by(new_businesses)
    series = []
    for i in range(days):
        d = start + timedelta(days=i)
        series.append({
            "day": d.isoformat(), "active": active.get(d, 0), "web": web.get(d, 0), "mobile": mobile.get(d, 0),
            "sign_ins": sign_in_by_day.get(d, 0), "orders": orders_by_day.get(d, 0),
            "messages": messages_by_day.get(d, 0), "new_businesses": businesses_by_day.get(d, 0),
        })

    distinct_clients = _count_by(await db.execute(
        select(UserActivity.client, func.count(distinct(UserActivity.user_id)))
        .where(UserActivity.day >= start).group_by(UserActivity.client)
    ))
    value_rows = await db.execute(
        select(Order.currency, func.coalesce(func.sum(Order.total_amount), 0))
        .where(Order.created_at >= start_at, Order.status.in_(REVENUE_STATUSES)).group_by(Order.currency)
    )
    direction = _count_by(await db.execute(
        select(Message.direction, func.count(Message.id)).where(Message.created_at >= start_at).group_by(Message.direction)
    ))
    period = {
        "active_people": await scalar(
            select(func.count(distinct(UserActivity.user_id))).where(UserActivity.day >= start)
        ),
        "web_people": distinct_clients.get("web", 0),
        "mobile_people": distinct_clients.get("mobile", 0),
        "sign_ins": sum(sign_in_by_day.values()),
        "failed_sign_ins": await scalar(
            select(func.count(LoginEvent.id)).where(LoginEvent.created_at >= start_at, LoginEvent.success.is_(False))
        ),
        "new_businesses": sum(businesses_by_day.values()),
        "new_people": await scalar(select(func.count(User.id)).where(User.created_at >= start_at)),
        "orders": sum(orders_by_day.values()),
        "order_value": [
            {"currency": c, "amount": Decimal(str(a)).quantize(Decimal("0.01"))}
            for c, a in value_rows if Decimal(str(a)) > 0
        ],
        "messages_in": direction.get("in", 0),
        "messages_out": direction.get("out", 0),
    }

    order_counts = select(Order.tenant_id.label("tid"), func.count(Order.id).label("n")) \
        .where(Order.created_at >= start_at).group_by(Order.tenant_id).subquery()
    active_counts = select(UserActivity.tenant_id.label("tid"), func.count(distinct(UserActivity.user_id)).label("n")) \
        .where(UserActivity.day >= start).group_by(UserActivity.tenant_id).subquery()
    last_seen = select(User.tenant_id.label("tid"), func.max(User.last_seen_at).label("at")) \
        .group_by(User.tenant_id).subquery()
    top_rows = await db.execute(
        select(Tenant.id, Tenant.name, func.coalesce(order_counts.c.n, 0), func.coalesce(active_counts.c.n, 0),
               last_seen.c.at)
        .outerjoin(order_counts, order_counts.c.tid == Tenant.id)
        .outerjoin(active_counts, active_counts.c.tid == Tenant.id)
        .outerjoin(last_seen, last_seen.c.tid == Tenant.id)
        .order_by(func.coalesce(order_counts.c.n, 0).desc(), func.coalesce(active_counts.c.n, 0).desc(), Tenant.name)
        .limit(8)
    )
    top = [
        {"id": tid, "name": name, "orders": int(o), "active_people": int(a), "last_active_at": at}
        for tid, name, o, a, at in top_rows if o or a
    ]
    return {"days": days, "start": start, "end": today, "totals": totals, "period": period, "series": series,
            "top_businesses": top}


# ---- businesses -------------------------------------------------------------------------------

async def _per_tenant(db: AsyncSession, query) -> dict:
    return {tid: int(n or 0) for tid, n in await db.execute(query)}


async def businesses(db: AsyncSession) -> list[dict]:
    week = _now().date() - timedelta(days=6)
    month_ago = _now() - timedelta(days=30)
    people = await _per_tenant(db, select(User.tenant_id, func.count(User.id)).group_by(User.tenant_id))
    active = await _per_tenant(db, select(UserActivity.tenant_id, func.count(distinct(UserActivity.user_id)))
                               .where(UserActivity.day >= week).group_by(UserActivity.tenant_id))
    branches = await _per_tenant(db, select(Branch.tenant_id, func.count(Branch.id))
                                 .where(Branch.is_active.is_(True)).group_by(Branch.tenant_id))
    customers = await _per_tenant(db, select(Customer.tenant_id, func.count(Customer.id)).group_by(Customer.tenant_id))
    orders = await _per_tenant(db, select(Order.tenant_id, func.count(Order.id)).group_by(Order.tenant_id))
    orders_30 = await _per_tenant(db, select(Order.tenant_id, func.count(Order.id))
                                  .where(Order.created_at >= month_ago).group_by(Order.tenant_id))
    last_seen = dict((await db.execute(select(User.tenant_id, func.max(User.last_seen_at)).group_by(User.tenant_id))).all())
    owners: dict = {}
    for tid, email in await db.execute(
        select(User.tenant_id, User.email).where(User.role == UserRole.OWNER.value).order_by(User.created_at)
    ):
        owners.setdefault(tid, email)
    out = []
    for t in await db.scalars(select(Tenant).order_by(Tenant.created_at.desc())):
        out.append({
            "id": t.id, "name": t.name, "slug": t.slug, "created_at": t.created_at,
            "suspended_at": t.suspended_at, "suspended_reason": t.suspended_reason,
            "owner_email": owners.get(t.id), "people": people.get(t.id, 0), "active_people_7d": active.get(t.id, 0),
            "branches": branches.get(t.id, 0), "customers": customers.get(t.id, 0),
            "orders": orders.get(t.id, 0), "orders_30d": orders_30.get(t.id, 0),
            "last_active_at": last_seen.get(t.id),
        })
    return out


async def _tenant(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    t = await db.get(Tenant, tenant_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found")
    return t


def person_row(u: User, business: str | None = None, branch: str | None = None) -> dict:
    return {
        "id": u.id, "tenant_id": u.tenant_id, "business": business, "email": u.email, "full_name": u.full_name,
        "role": u.role, "is_active": u.is_active, "branch": branch, "created_at": u.created_at,
        "last_login_at": u.last_login_at, "last_seen_at": u.last_seen_at,
        "is_platform_admin": is_platform_admin(u),
    }


async def business_detail(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    t = await _tenant(db, tenant_id)
    month_ago = _now() - timedelta(days=30)
    branch_rows = list(await db.scalars(
        select(Branch).where(Branch.tenant_id == t.id).order_by(Branch.is_default.desc(), Branch.name)
    ))
    branch_names = {b.id: b.name for b in branch_rows}
    units = {u.branch_id: u for u in await db.scalars(select(ZatcaUnit).where(ZatcaUnit.tenant_id == t.id))}
    people = [
        person_row(u, t.name, branch_names.get(u.branch_id))
        for u in await db.scalars(select(User).where(User.tenant_id == t.id).order_by(User.created_at))
    ]

    async def count(model, *where) -> int:
        return int(await db.scalar(select(func.count(model.id)).where(model.tenant_id == t.id, *where)) or 0)

    erp = await db.scalar(select(IntegrationConnection).where(IntegrationConnection.tenant_id == t.id))
    sign_ins = list(await db.scalars(
        select(LoginEvent).where(LoginEvent.tenant_id == t.id).order_by(LoginEvent.created_at.desc()).limit(15)
    ))
    return {
        "id": t.id, "name": t.name, "slug": t.slug, "timezone": t.timezone, "created_at": t.created_at,
        "suspended_at": t.suspended_at, "suspended_reason": t.suspended_reason,
        "counts": {
            "customers": await count(Customer), "products": await count(Product), "orders": await count(Order),
            "orders_30d": await count(Order, Order.created_at >= month_ago),
            "invoices": await count(SalesInvoice), "conversations": await count(Conversation),
        },
        "people": people,
        "branches": [
            {
                "id": b.id, "name": b.name, "city": b.city, "is_default": b.is_default, "is_active": b.is_active,
                "whatsapp_connected": bool(b.whatsapp_phone_number_id and b.whatsapp_access_token),
                "whatsapp_number": b.whatsapp_display_number,
                "zatca": units[b.id].status if b.id in units else None,
                "zatca_environment": units[b.id].environment if b.id in units else None,
            }
            for b in branch_rows
        ],
        "erp": {
            "provider": erp.provider, "status": erp.status, "server_version": erp.server_version,
            "last_pull_at": erp.last_pull_at, "last_error": erp.last_error,
        } if erp else None,
        "sign_ins": [_sign_in_row(e) for e in sign_ins],
    }


async def suspend(db: AsyncSession, actor: User, tenant_id: uuid.UUID, reason: str) -> Tenant:
    t = await _tenant(db, tenant_id)
    if t.id == actor.tenant_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You can't suspend your own business")
    if t.suspended_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This business is already suspended")
    t.suspended_at, t.suspended_reason = _now(), reason.strip()[:255]
    audit(db, actor, "business.suspend", target_type="business", target_id=t.id, target_label=t.name,
          detail={"reason": t.suspended_reason})
    await db.commit()
    return t


async def reactivate(db: AsyncSession, actor: User, tenant_id: uuid.UUID) -> Tenant:
    t = await _tenant(db, tenant_id)
    if t.suspended_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This business isn't suspended")
    t.suspended_at, t.suspended_reason = None, None
    audit(db, actor, "business.reactivate", target_type="business", target_id=t.id, target_label=t.name)
    await db.commit()
    return t


# ---- people -----------------------------------------------------------------------------------

async def people(db: AsyncSession, *, q: str | None, tenant_id: uuid.UUID | None, role: str | None,
                 state: str | None, limit: int = 300) -> list[dict]:
    query = select(User, Tenant.name, Branch.name).join(Tenant, Tenant.id == User.tenant_id) \
        .outerjoin(Branch, Branch.id == User.branch_id)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(User.email.ilike(like), User.full_name.ilike(like), Tenant.name.ilike(like)))
    if tenant_id:
        query = query.where(User.tenant_id == tenant_id)
    if role:
        query = query.where(User.role == role)
    if state == "active":
        query = query.where(User.is_active.is_(True))
    elif state == "inactive":
        query = query.where(User.is_active.is_(False))
    elif state == "online":
        query = query.where(User.last_seen_at >= _now() - ONLINE_WINDOW)
    query = query.order_by(User.last_seen_at.desc().nulls_last(), User.created_at.desc()).limit(limit)
    return [person_row(u, business, branch) for u, business, branch in await db.execute(query)]


async def person(db: AsyncSession, user_id: uuid.UUID) -> dict:
    row = (await db.execute(
        select(User, Tenant.name, Branch.name).join(Tenant, Tenant.id == User.tenant_id)
        .outerjoin(Branch, Branch.id == User.branch_id).where(User.id == user_id)
    )).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    return person_row(*row)


async def _person(db: AsyncSession, user_id: uuid.UUID) -> User:
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    return u


async def _other_active_owner(db: AsyncSession, u: User) -> bool:
    return bool(await db.scalar(
        select(func.count(User.id)).where(
            User.tenant_id == u.tenant_id, User.id != u.id, User.role == UserRole.OWNER.value, User.is_active.is_(True),
        )
    ))


async def update_person(db: AsyncSession, actor: User, user_id: uuid.UUID, *, is_active: bool | None,
                        role: str | None) -> User:
    from app.modules.users.service import _branch_for

    u = await _person(db, user_id)
    changes: dict = {}
    if is_active is not None and is_active != u.is_active:
        if u.id == actor.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "You can't switch off your own account")
        if not is_active and u.role == UserRole.OWNER.value and not await _other_active_owner(db, u):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "This is the business's only owner. Make someone else owner first.")
        u.is_active = is_active
        changes["is_active"] = is_active
    if role is not None and role != u.role:
        try:
            role = UserRole(role).value
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown role '{role}'")
        if role == UserRole.DEMO.value:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The demo role is set only by the demo script")
        if u.role == UserRole.OWNER.value and not await _other_active_owner(db, u):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "This is the business's only owner. Make someone else owner first.")
        changes["role"] = {"from": u.role, "to": role}
        u.role = role
        u.branch_id = await _branch_for(db, u.tenant_id, role, u.branch_id)
    if not changes:
        return u
    tenant = await db.get(Tenant, u.tenant_id)
    audit(db, actor, "person.update", target_type="person", target_id=u.id,
          target_label=f"{u.email} ({tenant.name if tenant else ''})", detail=changes)
    await db.commit()
    await db.refresh(u)
    return u


async def set_password(db: AsyncSession, actor: User, user_id: uuid.UUID, password: str) -> User:
    u = await _person(db, user_id)
    if len(password) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The password must be at least 8 characters")
    u.password_hash = hash_password(password)
    if u.id != actor.id:
        u.token_version += 1  # the old password's sessions end
    audit(db, actor, "person.password", target_type="person", target_id=u.id, target_label=u.email)
    await db.commit()
    await db.refresh(u)
    return u


async def sign_out_everywhere(db: AsyncSession, actor: User, user_id: uuid.UUID) -> User:
    u = await _person(db, user_id)
    if u.id == actor.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Use Sign out to end your own session")
    u.token_version += 1
    audit(db, actor, "person.sign_out", target_type="person", target_id=u.id, target_label=u.email)
    await db.commit()
    await db.refresh(u)
    return u


# ---- sign-ins and the audit log ---------------------------------------------------------------

def _sign_in_row(e: LoginEvent, business: str | None = None) -> dict:
    return {"id": e.id, "at": e.created_at, "email": e.email, "business": business, "client": e.client,
            "success": e.success, "reason": e.reason, "ip": e.ip}


async def sign_ins(db: AsyncSession, *, failed_only: bool, limit: int = 200) -> list[dict]:
    q = select(LoginEvent, Tenant.name).outerjoin(Tenant, Tenant.id == LoginEvent.tenant_id)
    if failed_only:
        q = q.where(LoginEvent.success.is_(False))
    rows = await db.execute(q.order_by(LoginEvent.created_at.desc()).limit(limit))
    return [_sign_in_row(e, name) for e, name in rows]


async def audit_log(db: AsyncSession, limit: int = 200) -> list[AdminAuditLog]:
    return list(await db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(limit)))


# ---- system health ----------------------------------------------------------------------------

def _config() -> list[dict]:
    s = settings
    llm_set = bool(s.LLM_API_KEY and s.LLM_API_KEY != "ollama") or "localhost" not in s.LLM_BASE_URL
    production = s.ENVIRONMENT.lower() == "production"
    return [
        {"key": "PLATFORM_ADMIN_EMAILS", "ok": bool(s.platform_admin_emails),
         "note": f"{len(s.platform_admin_emails)} Stonic admin(s)" if s.platform_admin_emails
         else "Empty: the console is hidden and the site switches have no effect"},
        {"key": "SECRETS_KEY", "ok": bool(s.SECRETS_KEY),
         "note": "Set" if s.SECRETS_KEY else "Empty: stored secrets fall back to JWT_SECRET. Set it once and never change it."},
        {"key": "LLM_API_KEY", "ok": llm_set,
         "note": f"Model {s.LLM_MODEL}" if llm_set else "Points at a local Ollama: the AI agent won't answer in production"},
        {"key": "WHATSAPP_APP_SECRET", "ok": bool(s.WHATSAPP_APP_SECRET),
         "note": "Set" if s.WHATSAPP_APP_SECRET else "Empty: WhatsApp webhook signatures aren't checked"},
        {"key": "WHATSAPP_VERIFY_TOKEN", "ok": bool(s.WHATSAPP_VERIFY_TOKEN),
         "note": "Set" if s.WHATSAPP_VERIFY_TOKEN else "Empty: Meta can't verify the webhook"},
        {"key": "SENTRY_DSN", "ok": bool(s.SENTRY_DSN),
         "note": "Errors are reported" if s.SENTRY_DSN else "Optional: errors are only in the server logs"},
        {"key": "GOOGLE_MAPS_API_KEY", "ok": bool(s.GOOGLE_MAPS_API_KEY),
         "note": "Set" if s.GOOGLE_MAPS_API_KEY else "Optional: Google search in Prospects is off"},
        {"key": "BILLING_BANK_DETAILS", "ok": bool(s.BILLING_BANK_DETAILS),
         "note": "Set" if s.BILLING_BANK_DETAILS else "Empty: invoices to businesses show no bank details"},
        {"key": "BILLING_SELLER_ADDRESS", "ok": bool(s.BILLING_SELLER_ADDRESS),
         "note": "Set" if s.BILLING_SELLER_ADDRESS else "Empty: invoices to businesses show no Stonic address"},
        {"key": "ERP_ALLOW_PRIVATE_URLS", "ok": not (production and s.ERP_ALLOW_PRIVATE_URLS),
         "note": "On (development only)" if s.ERP_ALLOW_PRIVATE_URLS else "Off"},
        {"key": "JOB_WORKER_ENABLED", "ok": s.JOB_WORKER_ENABLED,
         "note": "Background jobs run in this server" if s.JOB_WORKER_ENABLED
         else "Off: run `python -m app.jobs.worker` separately or nothing is sent"},
    ]


async def system(db: AsyncSession) -> dict:
    now = _now()
    started = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
        latency = round((time.perf_counter() - started) * 1000, 1)
        size = await db.scalar(text("SELECT pg_database_size(current_database())"))
        version = await db.scalar(text("SHOW server_version"))
        database = {"ok": True, "latency_ms": latency, "size_mb": round((size or 0) / 1048576, 1), "version": version}
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        database = {"ok": False, "error": str(exc)[:300]}

    day_ago = now - timedelta(hours=24)
    kinds: dict = {}
    for kind, st, n in await db.execute(
        select(Job.kind, Job.status, func.count(Job.id))
        .where(or_(Job.status.in_(("queued", "running", "failed")), Job.finished_at >= day_ago))
        .group_by(Job.kind, Job.status)
    ):
        row = kinds.setdefault(kind, {"kind": kind, "queued": 0, "running": 0, "failed": 0, "done_24h": 0})
        key = "done_24h" if st == "done" else st
        if key in row:
            row[key] += int(n)
    oldest = await db.scalar(select(func.min(Job.run_after)).where(Job.status == "queued", Job.run_after <= now))
    failed = await db.execute(
        select(Job, Tenant.name).outerjoin(Tenant, Tenant.id == Job.tenant_id)
        .where(Job.status == "failed").order_by(Job.finished_at.desc().nulls_last()).limit(50)
    )

    zatca_docs = _count_by(await db.execute(select(ZatcaDocument.status, func.count(ZatcaDocument.id))
                                            .group_by(ZatcaDocument.status)))
    zatca_units = _count_by(await db.execute(select(ZatcaUnit.status, func.count(ZatcaUnit.id)).group_by(ZatcaUnit.status)))
    expiring = await db.execute(
        select(ZatcaUnit, Tenant.name, Branch.name).join(Tenant, Tenant.id == ZatcaUnit.tenant_id)
        .join(Branch, Branch.id == ZatcaUnit.branch_id)
        .where(ZatcaUnit.certificate_expires_at.is_not(None), ZatcaUnit.certificate_expires_at <= now + timedelta(days=30))
        .order_by(ZatcaUnit.certificate_expires_at)
    )

    week_ago = now - timedelta(days=7)
    erp_failed = {cid: int(n) for cid, n in await db.execute(
        select(IntegrationEvent.connection_id, func.count(IntegrationEvent.id))
        .where(IntegrationEvent.status == "failed", IntegrationEvent.updated_at >= week_ago)
        .group_by(IntegrationEvent.connection_id)
    )}
    erp = await db.execute(
        select(IntegrationConnection, Tenant.name).join(Tenant, Tenant.id == IntegrationConnection.tenant_id)
        .order_by(Tenant.name)
    )

    wa_branches = await db.execute(
        select(func.count(Branch.id), func.count(Branch.id).filter(
            and_(Branch.whatsapp_phone_number_id.is_not(None), Branch.whatsapp_access_token.is_not(None))
        ))
    )
    total_branches, connected = wa_branches.one()
    wa_messages = _count_by(await db.execute(
        select(Message.direction, func.count(Message.id)).where(Message.created_at >= day_ago).group_by(Message.direction)
    ))
    last_inbound = await db.scalar(select(func.max(Message.created_at)).where(Message.direction == "in"))

    return {
        "checked_at": now,
        "server": {
            "environment": settings.ENVIRONMENT, "version": "0.1.0", "python": host.python_version(),
            "started_at": STARTED_AT, "uptime_seconds": int(time.monotonic() - _STARTED_MONO),
            "worker_enabled": settings.JOB_WORKER_ENABLED,
        },
        "database": database,
        "jobs": {
            "kinds": sorted(kinds.values(), key=lambda r: (-r["failed"], -r["queued"], r["kind"])),
            "oldest_waiting_seconds": int((now - oldest).total_seconds()) if oldest else 0,
            "failed": [
                {"id": j.id, "kind": j.kind, "business": name, "attempts": j.attempts, "max_attempts": j.max_attempts,
                 "last_error": (j.last_error or "")[:500], "finished_at": j.finished_at, "created_at": j.created_at}
                for j, name in failed
            ],
        },
        "zatca": {
            "documents": {k: zatca_docs.get(k, 0) for k in ("queued", "cleared", "reported", "rejected", "blocked")},
            "units": zatca_units,
            "expiring": [
                {"business": t, "branch": b, "environment": u.environment, "expires_at": u.certificate_expires_at}
                for u, t, b in expiring
            ],
        },
        "erp": [
            {"business": name, "provider": c.provider, "status": c.status, "server_version": c.server_version,
             "last_pull_at": c.last_pull_at, "last_error": c.last_error, "failed_7d": erp_failed.get(c.id, 0)}
            for c, name in erp
        ],
        "whatsapp": {
            "branches": int(total_branches or 0), "connected": int(connected or 0),
            "messages_in_24h": wa_messages.get("in", 0), "messages_out_24h": wa_messages.get("out", 0),
            "last_inbound_at": last_inbound,
        },
        "config": _config(),
    }


async def _job(db: AsyncSession, job_id: uuid.UUID) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


async def retry_job(db: AsyncSession, actor: User, job_id: uuid.UUID) -> Job:
    job = await _job(db, job_id)
    if job.status not in ("failed", "discarded"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Only failed jobs can be retried (this one is {job.status})")
    job.status, job.attempts, job.run_after = "queued", 0, _now()
    job.finished_at = job.locked_at = None
    audit(db, actor, "job.retry", target_type="job", target_id=job.id, target_label=job.kind)
    await db.commit()
    return job


async def discard_job(db: AsyncSession, actor: User, job_id: uuid.UUID) -> Job:
    job = await _job(db, job_id)
    if job.status not in ("failed", "queued"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Only failed or waiting jobs can be discarded (this one is {job.status})")
    job.status, job.finished_at = "discarded", _now()
    audit(db, actor, "job.discard", target_type="job", target_id=job.id, target_label=job.kind)
    await db.commit()
    return job