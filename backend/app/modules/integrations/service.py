"""Connecting an ERP, the mapping screen, running syncs and reporting on them.

One connection per business, to one of the connectors in PROVIDERS (Odoo,
SAP Business One, Dynamics 365 Business Central). Each connector module has
the same functions (discover, defaults, problems, clean_setting, push_*,
fetch_catalog, balances), so everything here works the same for all of them.

The flow on the dashboard:
1. connect: the login is checked against the ERP and saved (sealed); a
   complete first mapping is proposed.
2. test and dry run: check the connection and see what the first price and
   stock sync would change, before anything is written.
3. settings: the owner checks the mapping and what to sync.
4. activate: from now on orders, invoices and payments are sent, and prices
   and stock are fetched every few minutes. Nothing from before this moment
   is sent.
5. health: is it working -- fresh prices, nothing stuck, no failures.

A wrong or expired login stops the scheduled price and stock fetches until
the connection is checked again (test, options or reconnect), so a broken
key doesn't hammer the ERP every few minutes.
"""
import logging
import time
import types
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
from app.db.models.job import Job
from app.db.models.order import Order
from app.jobs.queue import ERP_PULL, ERP_PUSH, enqueue
from app.modules.accounts import service as accounts
from app.modules.integrations import catalog, dynamics_bc, hooks, odoo, sap_b1, store
from app.modules.integrations.base import SYNC_LABEL, Skip, SyncProblem
from app.modules.integrations.errors import ErpAuthError, ErpError, ErpUnavailable

logger = logging.getLogger("salesman.integrations")

CONNECTORS = {"odoo": odoo, "sap_b1": sap_b1, "dynamics_bc": dynamics_bc}
PROVIDERS = {
    "odoo": {"name": "Odoo", "available": True},
    "sap_b1": {"name": "SAP Business One", "available": True},
    "dynamics_bc": {"name": "Dynamics 365 Business Central", "available": True},
    "zoho_books": {"name": "Zoho Books", "available": False},
    "qoyod": {"name": "Qoyod", "available": False},
}
SETTING_KEYS = {
    "company_id", "sales_journal_id", "taxes", "payment_journals", "branches", "push_orders", "validate_deliveries",
    "push_invoices", "push_payments", "pull_catalog", "pull_interval_minutes", "adjustment_account",
}
KEEP_CATALOG_EVENTS = 50
AUTH_FAILED = "auth_failed_at"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def connector(conn_or_provider):
    key = conn_or_provider if isinstance(conn_or_provider, str) else conn_or_provider.provider
    return CONNECTORS[key]


def connect_fields() -> dict:
    return {k: m.CONNECT_FIELDS for k, m in CONNECTORS.items()}


async def get_connection(db: AsyncSession, tenant_id: uuid.UUID) -> IntegrationConnection | None:
    return await db.scalar(select(IntegrationConnection).where(IntegrationConnection.tenant_id == tenant_id))


async def require_connection(db: AsyncSession, tenant_id: uuid.UUID) -> IntegrationConnection:
    conn = await get_connection(db, tenant_id)
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No ERP is connected")
    return conn


def client_for(conn: IntegrationConnection):
    return connector(conn).open_client(conn.base_url, conn.database, conn.username, open_(conn.secret), conn.settings,
                                       api=conn.api, version=conn.server_version)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ErpUnavailable):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"{exc} Try again in a minute.")
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


async def _branches(db: AsyncSession, tenant_id: uuid.UUID) -> list[Branch]:
    return list(await db.scalars(select(Branch).where(Branch.tenant_id == tenant_id).order_by(Branch.name)))


def _clear_auth(conn: IntegrationConnection) -> None:
    if (conn.settings or {}).get(AUTH_FAILED):
        conn.settings = {k: v for k, v in conn.settings.items() if k != AUTH_FAILED}


def _mark_auth(conn: IntegrationConnection, exc: Exception) -> None:
    conn.last_error = str(exc)
    conn.settings = {**(conn.settings or {}), AUTH_FAILED: _now().isoformat()}


# ---- connecting -----------------------------------------------------------------------------

async def connect(db: AsyncSession, tenant_id: uuid.UUID, *, provider: str, url: str | None, database: str | None,
                  username: str | None, api_key: str | None, tenant: str | None = None) -> tuple[IntegrationConnection, dict]:
    if provider not in PROVIDERS or not PROVIDERS[provider]["available"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{PROVIDERS.get(provider, {}).get('name', provider)} is not available yet")
    module = connector(provider)
    conn = await get_connection(db, tenant_id)
    if conn is not None and conn.provider != provider:
        raise HTTPException(status.HTTP_409_CONFLICT, "Disconnect the current system before connecting another one")
    key = (api_key or "").strip() or (open_(conn.secret) if conn is not None else "")
    if not key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter the API key" if provider == "odoo" else
                            "Enter the password" if provider == "sap_b1" else "Enter the client secret")
    current = dict(conn.settings or {}) if conn is not None else {}
    if tenant is not None:
        current["aad_tenant"] = tenant.strip() or None
    client = module.open_client((url or "").strip(), (database or "").strip() or None, (username or "").strip() or None,
                                key, current)
    try:
        async with client:
            options = await module.discover(client)
    except (ErpError, ErpUnavailable) as exc:
        raise _http_error(exc) from exc
    if not options["companies"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"This {module.NAME} user can't see any company")

    acct = await accounts.get_settings(db, tenant_id)
    branches = await _branches(db, tenant_id)
    if conn is None:
        conn = IntegrationConnection(tenant_id=tenant_id, provider=provider, status="draft", settings={},
                                     base_url=client.url, secret=seal(key))
        db.add(conn)
    conn.base_url, conn.database, conn.username = client.url, client.database, client.username
    conn.secret, conn.api, conn.server_version, conn.last_error = seal(key), client.api, client.version, None
    settings = module.defaults(options, branches, acct, current)
    if current.get("aad_tenant"):
        settings["aad_tenant"] = current["aad_tenant"]
    conn.settings = settings
    await db.commit()
    await db.refresh(conn)
    return conn, options


async def options(db: AsyncSession, conn: IntegrationConnection) -> dict:
    module = connector(conn)
    try:
        async with client_for(conn) as client:
            found = await module.discover(client)
    except ErpAuthError as exc:
        _mark_auth(conn, exc)
        await db.commit()
        raise _http_error(exc) from exc
    except (ErpError, ErpUnavailable) as exc:
        raise _http_error(exc) from exc
    changed = conn.api != found["api"] or conn.server_version != found["version"] \
        or (conn.settings or {}).get("fields") != found["fields"] or (conn.settings or {}).get(AUTH_FAILED)
    if changed:
        conn.api, conn.server_version = found["api"], found["version"]
        conn.settings = {**conn.settings, "fields": found["fields"]}
        _clear_auth(conn)
        if conn.last_error and "refused" in conn.last_error:
            conn.last_error = None
        await db.commit()
    return found


async def update_settings(db: AsyncSession, conn: IntegrationConnection, data: dict) -> IntegrationConnection:
    module = connector(conn)
    new = dict(conn.settings)
    for key, value in data.items():
        if key not in SETTING_KEYS or value is None:
            continue
        if key == "pull_interval_minutes":
            value = min(max(int(value), 5), 24 * 60)
        else:
            try:
                value = module.clean_setting(key, value)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{key.replace('_', ' ')}: {exc}") from exc
        if key == "branches":  # merged per branch: sending one branch leaves the others as they are
            value = {**(new.get("branches") or {}), **value}
        new[key] = value
    if data.get("company_id") is not None and new.get("company_id") != conn.settings.get("company_id"):
        new["walkin_partner_id"] = None
    conn.settings = new
    await db.commit()
    await db.refresh(conn)
    return conn


async def problems(db: AsyncSession, conn: IntegrationConnection, found: dict | None = None) -> list[str]:
    acct = await accounts.get_settings(db, conn.tenant_id)
    out = connector(conn).problems(conn.settings or {}, await _branches(db, conn.tenant_id), acct, found)
    if (conn.settings or {}).get(AUTH_FAILED):
        out.insert(0, f"{connector(conn).NAME} refused the login. Check it with Test connection, or reconnect.")
    return out


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


# ---- checking before going live ---------------------------------------------------------------

async def test_connection(db: AsyncSession, conn: IntegrationConnection) -> dict:
    """Log in and read the setup, timing it. Never raises for ERP trouble: the answer says what is wrong."""
    module = connector(conn)
    started = time.monotonic()
    try:
        async with client_for(conn) as client:
            found = await module.discover(client)
    except ErpAuthError as exc:
        _mark_auth(conn, exc)
        await db.commit()
        return {"ok": False, "kind": "login", "message": str(exc), "latency_ms": int((time.monotonic() - started) * 1000)}
    except ErpUnavailable as exc:
        return {"ok": False, "kind": "unreachable", "message": str(exc),
                "latency_ms": int((time.monotonic() - started) * 1000)}
    except ErpError as exc:
        return {"ok": False, "kind": "refused", "message": str(exc),
                "latency_ms": int((time.monotonic() - started) * 1000)}
    latency = int((time.monotonic() - started) * 1000)
    _clear_auth(conn)
    if conn.last_error and ("refused" in conn.last_error or "login" in conn.last_error.lower()):
        conn.last_error = None
    conn.api, conn.server_version = found["api"], found["version"]
    await db.commit()
    return {
        "ok": True, "kind": "ok", "latency_ms": latency, "version": found["version"],
        "message": f"Connected to {module.NAME} {found['version'] or ''}".strip() + f" in {latency} ms.",
        "companies": len(found["companies"]), "warehouses": len(found["warehouses"]),
        "price_lists": len(found["pricelists"]), "taxes": len(found["taxes"]),
        "problems": await problems(db, conn, found),
    }


async def dry_run(db: AsyncSession, conn: IntegrationConnection) -> dict:
    """What the next price and stock sync would change, without writing anything."""
    module = connector(conn)
    view = types.SimpleNamespace(
        id=conn.id, tenant_id=conn.tenant_id, connected_at=conn.connected_at, provider=conn.provider,
        settings={**(conn.settings or {}), "pull_catalog": True},
    )
    try:
        async with client_for(conn) as client:
            cat = await module.fetch_catalog(db, view, client)
    except SyncProblem as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except (ErpError, ErpUnavailable) as exc:
        raise _http_error(exc) from exc
    return await catalog.preview(db, conn, cat)   # connectors only read while fetching: nothing to undo


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
    "order.confirmed": "push_order",
    "order.delivered": "deliver_order",
    "order.cancelled": "cancel_order",
    "invoice": "push_invoice",
    "payment": "push_payment",
    "payment.void": "void_payment",
    "customer": "push_customer",
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
    push = getattr(connector(conn), _PUSH[action])
    try:
        async with client_for(conn) as client:
            result = await push(db, conn, client, record)
    except Skip as exc:
        await db.commit()  # keep links to anything already created in the ERP
        if not exc.quiet:
            await store.record(db, conn, direction="push", action=action, local_key=record_id, label=label,
                               status="skipped", message=str(exc))
            await db.commit()
        return "skipped"
    except ErpUnavailable as exc:
        await db.commit()  # keep links to anything already created in the ERP
        await store.record(db, conn, direction="push", action=action, local_key=record_id, label=label,
                           status="failed", message=f"{exc}. Retrying automatically.")
        await db.commit()
        raise
    except (SyncProblem, ErpError) as exc:
        await db.commit()  # keep links to anything already created in the ERP
        conn = await db.get(IntegrationConnection, conn.id)
        if isinstance(exc, ErpAuthError):
            _mark_auth(conn, exc)
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
    module = connector(conn)
    started = _now()
    key = started.strftime("%Y%m%dT%H%M%S%f")
    try:
        async with client_for(conn) as client:
            result = await catalog.apply(db, conn, await module.fetch_catalog(db, conn, client))
    except Skip:
        await db.rollback()
        return "skipped"
    except (SyncProblem, ErpError, ErpUnavailable) as exc:
        await db.rollback()
        conn = await db.get(IntegrationConnection, conn_id)
        conn.last_error = str(exc)
        if isinstance(exc, ErpAuthError):
            _mark_auth(conn, exc)
        await store.record(db, conn, direction="pull", action="catalog", local_key=key, label=SYNC_LABEL,
                           status="failed", message=str(exc))
        await _finish_pull(db, conn, started)
        return "failed"
    conn = await db.get(IntegrationConnection, conn_id)
    conn.last_error = None
    await store.record(db, conn, direction="pull", action="catalog", local_key=key, label=SYNC_LABEL,
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
    queued = 0
    for conn in due:
        s = conn.settings or {}
        if not s.get("pull_catalog") or s.get(AUTH_FAILED):
            continue   # switched off, or the login is broken: wait until it is checked again
        interval = int(s.get("pull_interval_minutes") or 15)
        conn.next_pull_at = now + timedelta(minutes=interval)
        await enqueue(db, ERP_PULL, {"connection_id": str(conn.id)}, tenant_id=conn.tenant_id,
                      dedupe_key=f"erp-pull:{conn.id}:{int(now.timestamp()) // 60}", max_attempts=2, commit=False)
        queued += 1
    await db.commit()
    return queued


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


async def health(db: AsyncSession, conn: IntegrationConnection) -> dict:
    """Is the connection working? One verdict and the checks behind it."""
    now = _now()
    s = conn.settings or {}
    checks = []

    def check(key: str, ok: bool | None, message: str, severity: str = "error") -> None:
        checks.append({"key": key, "status": "ok" if ok else ("info" if ok is None else severity), "message": message})

    if conn.status != "active":
        check("switched_on", None, "The connection is switched off: nothing is sent or fetched.")
    else:
        check("switched_on", True, "Switched on.")
    if s.get(AUTH_FAILED):
        check("login", False, f"{connector(conn).NAME} refused the login: {conn.last_error or ''}".strip())
    else:
        check("login", True, "Login accepted.")

    interval = int(s.get("pull_interval_minutes") or 15)
    if conn.status == "active" and s.get("pull_catalog"):
        if conn.last_pull_at is None:
            check("prices", None, "Prices and stock haven't been fetched yet.")
        else:
            age = (now - conn.last_pull_at).total_seconds() / 60
            last = await db.scalar(select(IntegrationEvent).where(
                IntegrationEvent.connection_id == conn.id, IntegrationEvent.action == "catalog",
            ).order_by(IntegrationEvent.created_at.desc()).limit(1))
            if last is not None and last.status == "failed":
                check("prices", False, f"The last price and stock fetch failed: {last.message}")
            elif age > interval * 3:
                check("prices", False, f"Prices and stock are {int(age)} minutes old (they refresh every {interval}).", "warning")
            else:
                check("prices", True, f"Prices and stock fetched {int(age)} minute(s) ago.")

    since = now - timedelta(hours=24)
    failed = await db.scalar(select(func.count()).select_from(IntegrationEvent).where(
        IntegrationEvent.connection_id == conn.id, IntegrationEvent.direction == "push",
        IntegrationEvent.status == "failed", IntegrationEvent.updated_at >= since,
    )) or 0
    check("sending", failed == 0, "Nothing failed to send in the last 24 hours." if failed == 0
          else f"{failed} record(s) failed to send in the last 24 hours. See Needs attention.")

    queued = (await db.execute(select(func.count(), func.min(Job.created_at)).where(
        Job.tenant_id == conn.tenant_id, Job.kind == ERP_PUSH, Job.status.in_(("queued", "running")),
    ))).one()
    waiting, oldest = queued[0] or 0, queued[1]
    if waiting and oldest is not None and (now - oldest) > timedelta(minutes=30):
        check("queue", False, f"{waiting} record(s) waiting to be sent, the oldest for "
                              f"{int((now - oldest).total_seconds() // 60)} minutes.", "warning")
    else:
        check("queue", True, f"{waiting} record(s) waiting to be sent." if waiting else "Nothing waiting to be sent.")

    worst = "error" if any(c["status"] == "error" for c in checks) else \
        "warning" if any(c["status"] == "warning" for c in checks) else "ok"
    verdict = {"error": "down", "warning": "degraded", "ok": "healthy"}[worst]
    if conn.status != "active" and verdict == "healthy":
        verdict = "off"
    return {"status": verdict, "checks": checks, "checked_at": now}


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


async def retry_failed(db: AsyncSession, conn: IntegrationConnection) -> int:
    """Send every failed record again (after fixing the mapping, say)."""
    if conn.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Switch the connection on first")
    events = list(await db.scalars(select(IntegrationEvent).where(
        IntegrationEvent.connection_id == conn.id, IntegrationEvent.direction == "push", IntegrationEvent.status == "failed",
    ).limit(500)))
    for event in events:
        await hooks.queue(db, conn.tenant_id, event.action, uuid.UUID(event.local_key), retry=event.attempts + 1)
        event.status, event.message = "pending", "Queued to send again"
    await db.commit()
    return len(events)


async def balances(db: AsyncSession, conn: IntegrationConnection) -> list[dict]:
    try:
        async with client_for(conn) as client:
            rows = await connector(conn).balances(db, conn, client)
    except (ErpError, ErpUnavailable) as exc:
        raise _http_error(exc) from exc
    for row in rows:
        row.setdefault("erp", row.get("odoo"))
    return rows
