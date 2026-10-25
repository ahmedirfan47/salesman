"""Cost import on activation, the job queue, the WhatsApp pipeline, health and the demo account."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.security import create_access_token, hash_password
from app.db.models.job import Job
from app.db.models.message import Message
from app.db.models.product import Product
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.session import get_session
from app.jobs import queue, worker
from app.main import app
from app.modules.pricing import service as pricing
from app.schemas.pricing import PriceLineIn, PriceListCreate

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def session_factory(db):
    """Hands the worker the test session (wrapped so `async with` doesn't close it)."""

    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    return lambda: _Ctx()


async def _tenant(db, **kw):
    t = Tenant(name="Al Rayyan Fresh", slug=f"t-{uuid.uuid4().hex[:10]}", **kw)
    db.add(t)
    await db.flush()
    return t


async def _user(db, tenant, role):
    u = User(tenant_id=tenant.id, email=f"{role}-{uuid.uuid4().hex[:6]}@x.co",
             password_hash=hash_password("pw-123456"), role=role)
    db.add(u)
    await db.flush()
    return u


def _auth(u):
    return {"Authorization": f"Bearer {create_access_token(u.id, u.tenant_id, u.role)}"}


# --- cost import ------------------------------------------------------------

async def test_activating_a_sheet_with_costs_sets_product_costs(db):
    t = await _tenant(db)
    await db.commit()
    pl = await pricing.create_price_list(db, t.id, PriceListCreate(lines=[
        PriceLineIn(sku="TOM-5", unit_price=Decimal("35"), quantity=10, currency="SAR", unit_cost=Decimal("24.50")),
        PriceLineIn(sku="POT-10", unit_price=Decimal("22"), quantity=5, currency="SAR"),
    ]))
    # nothing changes until the list is activated
    tom = await db.scalar(select(Product).where(Product.tenant_id == t.id, Product.sku == "TOM-5"))
    assert tom.cost_price is None

    await pricing.activate_price_list(db, t.id, pl.id)
    tom = await db.scalar(select(Product).where(Product.tenant_id == t.id, Product.sku == "TOM-5"))
    pot = await db.scalar(select(Product).where(Product.tenant_id == t.id, Product.sku == "POT-10"))
    await db.refresh(tom)
    await db.refresh(pot)
    assert tom.cost_price == Decimal("24.50") and tom.cost_currency == "SAR"
    assert pot.cost_price is None


async def test_sheet_without_costs_keeps_costs_entered_by_hand(db):
    t = await _tenant(db)
    p = Product(tenant_id=t.id, sku="TOM-5", name_en="Tomatoes", cost_price=Decimal("20"), cost_currency="SAR")
    db.add(p)
    await db.commit()
    pl = await pricing.create_price_list(db, t.id, PriceListCreate(lines=[
        PriceLineIn(sku="TOM-5", unit_price=Decimal("35"), quantity=10, currency="SAR"),
    ]))
    await pricing.activate_price_list(db, t.id, pl.id)
    await db.refresh(p)
    assert p.cost_price == Decimal("20")


# --- job queue ----------------------------------------------------------------

async def test_enqueue_is_idempotent_with_dedupe_key(db):
    assert await queue.enqueue(db, "noop", {"a": 1}, dedupe_key="k1") is True
    assert await queue.enqueue(db, "noop", {"a": 2}, dedupe_key="k1") is False
    assert await db.scalar(select(func.count(Job.id))) == 1


async def test_claim_complete_and_retry_with_backoff(db):
    await queue.enqueue(db, "noop", {}, max_attempts=2)
    job = await queue.claim(db)
    assert job.status == "running" and job.attempts == 1
    assert await queue.claim(db) is None  # already taken

    final = await queue.mark_failed(db, job.id, "boom")
    assert final is False
    await db.refresh(job)
    assert job.status == "queued" and job.run_after > datetime.now(timezone.utc)

    job.run_after = datetime.now(timezone.utc) - timedelta(seconds=1)  # skip the wait
    await db.commit()
    job = await queue.claim(db)
    assert job.attempts == 2
    assert await queue.mark_failed(db, job.id, "boom again") is True
    await db.refresh(job)
    assert job.status == "failed" and job.last_error == "boom again"


async def test_abandoned_running_job_is_reclaimed(db):
    await queue.enqueue(db, "noop", {})
    job = await queue.claim(db)
    job.locked_at = datetime.now(timezone.utc) - queue.STALE_AFTER - timedelta(minutes=1)
    await db.commit()
    again = await queue.claim(db)
    assert again is not None and again.id == job.id and again.attempts == 2


async def test_worker_runs_registered_handler(db, session_factory):
    seen = []

    @worker.handler("test.echo")
    async def _echo(session, payload):
        seen.append(payload["x"])

    await queue.enqueue(db, "test.echo", {"x": 42})
    assert await worker.run_once(session_factory) is True
    assert seen == [42]
    job = await db.scalar(select(Job))
    await db.refresh(job)
    assert job.status == "done"
    assert await worker.run_once(session_factory) is False


async def test_worker_records_unknown_kind_as_failure(db, session_factory):
    await queue.enqueue(db, "does.not.exist", {}, max_attempts=1)
    await worker.run_once(session_factory)
    job = await db.scalar(select(Job))
    await db.refresh(job)
    assert job.status == "failed" and "No handler" in job.last_error


# --- WhatsApp pipeline ----------------------------------------------------------

def _webhook(phone_number_id, text="Price of tomatoes?", wa_id="wamid.1"):
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": phone_number_id},
        "contacts": [{"profile": {"name": "Khalid"}}],
        "messages": [{"type": "text", "from": "966500000001", "id": wa_id, "text": {"body": text}}],
    }}]}]}


async def test_webhook_queues_once_and_never_runs_the_agent_inline(db, client, monkeypatch):
    import app.api.v1.whatsapp as wa_route
    import app.channels.whatsapp.service as wa

    async def _boom(*a, **k):
        raise AssertionError("agent must not run inside the webhook")

    monkeypatch.setattr(wa, "run_agent", _boom)

    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(wa_route, "SessionLocal", lambda: _Ctx())
    body = _webhook("PNID-1")
    r1 = await client.post("/api/v1/webhooks/whatsapp", json=body)
    r2 = await client.post("/api/v1/webhooks/whatsapp", json=body)  # Meta re-delivery
    assert r1.status_code == r2.status_code == 200
    jobs = list(await db.scalars(select(Job)))
    assert len(jobs) == 1 and jobs[0].kind == queue.WHATSAPP_INBOUND_TEXT


async def test_inbound_message_is_answered_once_even_if_processed_twice(db, monkeypatch):
    import app.channels.whatsapp.service as wa

    t = await _tenant(db, whatsapp_phone_number_id="PNID-2")
    await db.commit()
    calls = []

    async def _agent(db_, tenant_id, name, history, text):
        calls.append(text)
        return {"reply": "Tomatoes are SAR 35 today."}

    monkeypatch.setattr(wa, "run_agent", _agent)
    for _ in range(2):
        await wa.process_incoming(db, "PNID-2", "966500000001", "Price of tomatoes?", "wamid.X", "Khalid")

    assert calls == ["Price of tomatoes?"]
    assert await db.scalar(select(func.count(Message.id)).where(Message.tenant_id == t.id)) == 2  # in + out
    sends = list(await db.scalars(select(Job).where(Job.kind == queue.WHATSAPP_SEND_TEXT)))
    assert len(sends) == 1 and sends[0].payload["body"] == "Tomatoes are SAR 35 today."


async def test_agent_failure_still_answers_the_customer(db, monkeypatch):
    import app.channels.whatsapp.service as wa

    await _tenant(db, whatsapp_phone_number_id="PNID-3")
    await db.commit()

    async def _agent(*a, **k):
        raise RuntimeError("LLM provider down")

    monkeypatch.setattr(wa, "run_agent", _agent)
    await wa.process_incoming(db, "PNID-3", "966500000002", "hello", "wamid.Y", None)
    send = await db.scalar(select(Job).where(Job.kind == queue.WHATSAPP_SEND_TEXT))
    assert "team member will follow up" in send.payload["body"]


# --- health -----------------------------------------------------------------------

async def test_readiness_reports_database_and_jobs(db, client):
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] == "ok" and body["jobs"]["failed_last_24h"] == 0


# --- demo account ---------------------------------------------------------------

async def test_demo_account_can_view_but_not_change(db, client):
    t = await _tenant(db)
    demo = await _user(db, t, "demo")
    await db.commit()

    assert (await client.get("/api/v1/analytics/summary", headers=_auth(demo))).status_code == 200
    assert (await client.get("/api/v1/orders", headers=_auth(demo))).status_code == 200
    me = (await client.get("/api/v1/auth/me", headers=_auth(demo))).json()
    assert "view_analytics" in me["capabilities"]

    r = await client.put("/api/v1/analytics/product-costs", headers=_auth(demo),
                         json={"items": [{"product_id": str(uuid.uuid4()), "cost_price": "1"}]})
    assert r.status_code == 403 and "read-only demo" in r.json()["detail"]
    r = await client.post("/api/v1/products", headers=_auth(demo), json={"sku": "X", "name_en": "X"})
    assert r.status_code == 403


async def test_demo_role_cannot_be_assigned_from_the_app(db, client):
    t = await _tenant(db)
    owner = await _user(db, t, "owner")
    await db.commit()
    r = await client.post("/api/v1/users", headers=_auth(owner),
                          json={"email": "x@example.com", "password": "pw-12345678", "role": "demo"})
    assert r.status_code == 422


async def test_seed_demo_builds_a_useful_dataset(db, client):
    from app.scripts.seed_demo import seed

    tenant = await seed(db, "demo@example.com", "demo-password-123")
    demo = await db.scalar(select(User).where(User.email == "demo@example.com"))
    assert demo.role == "demo"

    s = (await client.get("/api/v1/analytics/summary?days=90", headers=_auth(demo))).json()
    assert s["order_count"] > 20 and s["currency"] == "SAR" and s["margin_percent"] is not None
    assert s["products_missing_cost"] == 2
    quiet = (await client.get("/api/v1/analytics/drifting-customers", headers=_auth(demo))).json()
    assert {c["name"] for c in quiet} >= {"Al Waha Market", "Green Valley Store"}
    esc = (await client.get("/api/v1/orders/escalations/open", headers=_auth(demo))).json()
    assert len(esc) == 1

    # rebuilding is repeatable
    again = await seed(db, "demo@example.com", "demo-password-123", reset=True)
    assert again.id != tenant.id