"""Connecting an ERP, the mapping screen, running syncs and reporting on them.

One connection per business. The flow on the dashboard:
1. connect: URL, database, user and API key are checked against the ERP and
   saved (sealed); a complete first mapping is proposed.
2. settings: the owner checks the mapping (company, warehouses per branch,
   tax, journals) and what to sync.
3. activate: from now on orders, invoices and payments are sent, and prices
   and stock are fetched every few minutes. Nothing from before this moment
   is sent.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_box import open_, seal
from app.db.models.accounts import CustomerPayment, SalesInvoice
from app.db.models.branch import Branch
from app.db.models.customer import Customer
from app.db.models.integration import IntegrationConnection, IntegrationEvent
from app.db.models.order import Order
from app.jobs.queue import ERP_PULL, enqueue
from app.modules.accounts import service as accounts
from app.modules.integrations import hooks, odoo, store
from app.modules.integrations.odoo_client import OdooAuthError, OdooClient, OdooError, OdooUnavailable

logger = logging.getLogger("salesman.integrations")

PROVIDERS = {
    "odoo": {"name": "Odoo", "available": True},
    "zoho_books": {"name": "Zoho Books", "available": False},
    "qoyod": {"name": "Qoyod", "available": False},
    "sap_b1": {"name": "SAP Business One", "available": False},
}
SETTING_KEYS = {
    "company_id", "sales_journal_id", "taxes", "payment_journals", "branches", "push_orders", "validate_deliveries",
    "push_invoices", "push_payments", "pull_catalog", "pull_interval_minutes",
}
KEEP_CATALOG_EVENTS = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_connection(db: AsyncSession, tenant_id: uuid.UUID) -> IntegrationConnection | None:
    return await db.scalar(select(IntegrationConnection).where(IntegrationConnection.tenant_id == tenant_id))


async def require_connection(db: AsyncSession, tenant_id: uuid.UUID) -> IntegrationConnection:
    conn = await get_connection(db, tenant_id)
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No ERP is connected")
    return conn


def client_for(conn: IntegrationConnection) -> OdooClient:
    return OdooClient(conn.base_url, conn.database, conn.username, open_(conn.secret), api=conn.api, version=conn.server_version)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, OdooUnavailable):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"{exc} Try again in a minute.")
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


async def _branches(db: AsyncSession, tenant_id: uuid.UUID) -> list[Branch]:
    return list(await db.scalars(select(Branch).where(Branch.tenant_id == tenant_id).order_by(Branch.name)))


# ---- connecting -----------------------------------------------------------------------------

async def connect(db: AsyncSession, tenant_id: uuid.UUID, *, provider: str, url: str, database: str | None,
                  username: str | None, api_key: str | None) -> tuple[IntegrationConnection, dict]:
    if provider not in PROVIDERS or not PROVIDERS[provider]["available"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{PROVIDERS.get(provider, {}).get('name', provider)} is not available yet")
    conn = await get_connection(db, tenant_id)
    if conn is not None and conn.provider != provider:
        raise HTTPException(status.HTTP_409_CONFLICT, "Disconnect the current system before connecting another one")
    key = (api_key or "").strip() or (open_(conn.secret) if conn is not None else "")
    if not key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter the API key")
    client = OdooClient(url, (database or "").strip() or None, (username or "").strip() or None, key)
    try:
        async with client:
            options = await odoo.discover(client)
    except (OdooError, OdooUnavailable) as exc:
        raise _http_error(exc) from exc
    if not options["companies"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This Odoo user can't see any company")

    acct = await accounts.get_settings(db, tenant_id)
    branches = await _branches(db, tenant_id)
    if conn is None:
        conn = IntegrationConnection(tenant_id=tenant_id, provider=provider, status="draft", settings={},
                                     base_url=client.url, secret=seal(key))
        db.add(conn)
    conn.base_url, conn.database, conn.username = client.url, client.database, client.username
    conn.secret, conn.api, conn.server_version, conn.last_error = seal(key), client.api, client.version, None
    conn.settings = odoo.defaults(options, branches, acct, conn.settings)
    await db.commit()
    await db.refresh(conn)
    return conn, options


async def options(db: AsyncSession, conn: IntegrationConnection) -> dict:
    try:
        async with client_for(conn) as client:
            found = await odoo.discover(client)
    except (OdooError, OdooUnavailable) as exc:
        raise _http_error(exc) from exc
    if conn.api != found["api"] or conn.server_version != found["version"] or (conn.settings or {}).get("fields") != found["fields"]:
        conn.api, conn.server_version = found["api"], found["version"]
        conn.settings = {**conn.settings, "fields": found["fields"]}
        await db.commit()
    return found


async def update_settings(db: AsyncSession, conn: IntegrationConnection, data: dict) -> IntegrationConnection:
    new = dict(conn.settings)
    for key, value in data.items():
        if key not in SETTING_KEYS or value is None:
            continue
        if key == "pull_interval_minutes":
            value = min(max(int(value), 5), 24 * 60)
        if key == "taxes":
            value = {odoo.rate_key(rate): int(tax) for rate, tax in value.items() if tax}
        if key == "payment_journals":
            value = {m: int(j) for m, j in value.items() if j and m in odoo.PAYMENT_METHODS}
        if key == "branches":  # merged per branch: sending one branch leaves the others as they are
            value = {**(new.get("branches") or {}), **{
                str(b): {"warehouse_id": int(m["warehouse_id"]) if m.get("warehouse_id") else None,
                         "pricelist_id": int(m["pricelist_id"]) if m.get("pricelist_id") else None}
                for b, m in value.items()
            }}
        new[key] = value
    if data.get("company_id") and data["company_id"] != conn.settings.get("company_id"):
        new["walkin_partner_id"] = None
    conn.settings = new
    await db.commit()
    await db.refresh(conn)
    return conn


async def problems(db: AsyncSession, conn: IntegrationConnection, found: dict | None = None) -> list[str]:
    acct = await accounts.get_settings(db, conn.tenant_id)
    return odoo.problems(conn.settings or {}, await _branches(db, conn.tenant_id), acct, found)


async def activate(db: AsyncSession, conn: IntegrationConnection) -> IntegrationConnection:
    found = await options(db, conn)
    todo = await problems(db, conn, found)
    if todo:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, " ".join(todo))
    conn.status = "active"
    conn.connected_at = conn.connected_at or _now()
    conn.next_pull_at = _now()
    conn.last_error = None
    await db.commit()
    await enqueue(db, ERP_PULL, {"connection_id": str(conn.id)}, tenant_id=conn.tenant_id,
                  dedupe_key=f"erp-pull:{conn.id}:on:{uuid.uuid4().hex}", max_attempts=3)
    await db.refresh(conn)
    return conn


async def pause(db: AsyncSession, conn: IntegrationConnection) -> IntegrationConnection:
    conn.status = "paused" if conn.connected_at else "draft"
    await db.commit()
    await db.refresh(conn)
    return conn


async def disconnect(db: AsyncSession, conn: IntegrationConnection) -> None:
    await db.delete(conn)
    await db.commit()


async def sync_now(db: AsyncSession, conn: IntegrationConnection) -> None:
    if conn.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Switch the connection on first")
    await enqueue(db, ERP_PULL, {"connection_id": str(conn.id)}, tenant_id=conn.tenant_id,
                  dedupe_key=f"erp-pull:{conn.id}:now:{uuid.uuid4().hex}", max_attempts=1)


# ---- running --------------------------------------------------------------------------------

async def _label(db: AsyncSession, action: str, record_id: uuid.UUID):
    """(label, record) for an action, or (None, None) when the record is gone."""
    if action.startswith("order."):
        order = await db.get(Order, record_id)
        return (order.order_number, order) if order else (None, None)
    if action == "invoice":
        inv = await db.get(SalesInvoice, record_id)
        return (inv.number, inv) if inv else (None, None)
    if action.startswith("payment"):
        pay = await db.get(CustomerPayment, record_id)
        return (pay.number, pay) if pay else (None, None)
    if action == "customer":
        c = await db.get(Customer, record_id)
        return ((c.company or c.name), c) if c else (None, None)
    return None, None


_PUSH = {
    "order.confirmed": odoo.push_order,
    "order.delivered": odoo.deliver_order,
    "order.cancelled": odoo.cancel_order,
    "invoice": odoo.push_invoice,
    "payment": odoo.push_payment,
    "payment.void": odoo.void_payment,
    "customer": odoo.push_customer,
}


async def run_push(db: AsyncSession, payload: dict) -> str:
    """Job handler. Raises only for temporary trouble, so the queue retries it."""
    conn = await db.get(IntegrationConnection, uuid.UUID(payload["connection_id"]))
    if conn is None or conn.status != "active":
        return "inactive"
    action, record_id = payload["action"], uuid.UUID(payload["id"])
    label, record = await _label(db, action, record_id)
    if record is None:
        return "gone"
    try:
        async with client_for(conn) as client:
            result = await _PUSH[action](db, conn, client, record)
    except odoo.Skip as exc:
        await db.commit()  # keep links to anything already created in the ERP
        if not exc.quiet:
            await store.record(db, conn, direction="push", action=action, local_key=record_id, label=label,
                               status="skipped", message=str(exc))
            await db.commit()
        return "skipped"
    except OdooUnavailable as exc:
        await db.commit()  # keep links to anything already created in the ERP
        await store.record(db, conn, direction="push", action=action, local_key=record_id, label=label,
                           status="failed", message=f"{exc}. Retrying automatically.")
        await db.commit()
        raise
    except (odoo.SyncProblem, OdooError) as exc:
        await db.commit()  # keep links to anything already created in the ERP
        conn = await db.get(IntegrationConnection, conn.id)
        if isinstance(exc, OdooAuthError):
            conn.last_error = str(exc)
        await store.record(db, conn, direction="push", action=action, local_key=record_id, label=label,
                           status="failed", message=str(exc))
        await db.commit()
        return "failed"
    await store.record(db, conn, direction="push", action=action, local_key=record_id, label=label,
                       status=result.status, message=result.message, external_ref=result.external_ref)
    if conn.last_error:
        conn.last_error = None
    await db.commit()
    return result.status


async def run_pull(db: AsyncSession, payload: dict) -> str:
    conn = await db.get(IntegrationConnection, uuid.UUID(payload["connection_id"]))
    if conn is None or conn.status != "active":
        return "inactive"
    conn_id = conn.id
    started = _now()
    key = started.strftime("%Y%m%dT%H%M%S%f")
    try:
        async with client_for(conn) as client:
            result = await odoo.pull_catalog(db, conn, client)
    except odoo.Skip:
        await db.rollback()
        return "skipped"
    except (odoo.SyncProblem, OdooError, OdooUnavailable) as exc:
        await db.rollback()
        conn = await db.get(IntegrationConnection, conn_id)
        conn.last_error = str(exc)
        await store.record(db, conn, direction="pull", action="catalog", local_key=key, label=odoo.SYNC_LABEL,
                           status="failed", message=str(exc))
        await _finish_pull(db, conn, started)
        return "failed"
    conn = await db.get(IntegrationConnection, conn_id)
    conn.last_error = None
    await store.record(db, conn, direction="pull", action="catalog", local_key=key, label=odoo.SYNC_LABEL,
                       status=result.status, message=result.message)
    await _finish_pull(db, conn, started)
    return result.status


async def _finish_pull(db: AsyncSession, conn: IntegrationConnection, started: datetime) -> None:
    conn.last_pull_at = started
    conn.next_pull_at = started + timedelta(minutes=int((conn.settings or {}).get("pull_interval_minutes") or 15))
    old = list(await db.scalars(
        select(IntegrationEvent.id).where(IntegrationEvent.connection_id == conn.id, IntegrationEvent.action == "catalog")
        .order_by(IntegrationEvent.created_at.desc()).offset(KEEP_CATALOG_EVENTS)
    ))
    if old:
        await db.execute(delete(IntegrationEvent).where(IntegrationEvent.id.in_(old)))
    await db.commit()


async def schedule_pulls(db: AsyncSession) -> int:
    """Called by the worker every minute: queue a price-and-stock fetch for each connection that is due."""
    now = _now()
    due = list(await db.scalars(
        select(IntegrationConnection).where(
            IntegrationConnection.status == "active",
            (IntegrationConnection.next_pull_at.is_(None)) | (IntegrationConnection.next_pull_at <= now),
        )
    ))
    for conn in due:
        if not (conn.settings or {}).get("pull_catalog"):
            continue
        interval = int((conn.settings or {}).get("pull_interval_minutes") or 15)
        conn.next_pull_at = now + timedelta(minutes=interval)
        await enqueue(db, ERP_PULL, {"connection_id": str(conn.id)}, tenant_id=conn.tenant_id,
                      dedupe_key=f"erp-pull:{conn.id}:{int(now.timestamp()) // 60}", max_attempts=2, commit=False)
    await db.commit()
    return len(due)


# ---- reporting ------------------------------------------------------------------------------

async def list_events(db: AsyncSession, conn: IntegrationConnection, *, status_: str | None = None,
                      limit: int = 100) -> list[IntegrationEvent]:
    q = select(IntegrationEvent).where(IntegrationEvent.connection_id == conn.id)
    if status_ == "attention":
        q = q.where(IntegrationEvent.status.in_(("failed", "warning")))
    elif status_:
        q = q.where(IntegrationEvent.status == status_)
    return list(await db.scalars(q.order_by(IntegrationEvent.updated_at.desc()).limit(limit)))


async def counts(db: AsyncSession, conn: IntegrationConnection) -> dict:
    rows = dict((await db.execute(
        select(IntegrationEvent.status, func.count()).where(
            IntegrationEvent.connection_id == conn.id, IntegrationEvent.direction == "push",
        ).group_by(IntegrationEvent.status)
    )).all())
    return {"ok": rows.get("ok", 0), "warning": rows.get("warning", 0), "failed": rows.get("failed", 0),
            "skipped": rows.get("skipped", 0)}


async def retry(db: AsyncSession, conn: IntegrationConnection, event_id: uuid.UUID) -> IntegrationEvent:
    event = await db.scalar(select(IntegrationEvent).where(IntegrationEvent.id == event_id,
                                                           IntegrationEvent.connection_id == conn.id))
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if conn.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Switch the connection on first")
    if event.direction == "pull":
        await sync_now(db, conn)
    else:
        await hooks.queue(db, conn.tenant_id, event.action, uuid.UUID(event.local_key), retry=event.attempts + 1)
        event.status, event.message = "pending", "Queued to send again"
        await db.commit()
    await db.refresh(event)
    return event


async def balances(db: AsyncSession, conn: IntegrationConnection) -> list[dict]:
    try:
        async with client_for(conn) as client:
            return await odoo.balances(db, conn, client)
    except (OdooError, OdooUnavailable) as exc:
        raise _http_error(exc) from exc