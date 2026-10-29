"""The Stonic Console: site switches, suspension, people, analytics, system health and the audit log."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import settings
from app.core.branches import default_branch
from app.core.security import create_access_token, hash_password
from app.db.models.job import Job
from app.db.models.order import Order
from app.db.models.platform import AdminAuditLog, LoginEvent, UserActivity
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.session import get_session
from app.main import app
from app.modules.platform import site

ADMIN = "ops@stonic-hq.com"
PW = "pw-123456"
WEB = {"X-Client": "web"}
MOBILE = {"X-Client": "mobile"}


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_session] = _override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture(autouse=True)
def _platform_admin(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", ADMIN)


async def _tenant(db, name="Al Rayyan Fresh"):
    t = Tenant(name=name, slug=f"t-{uuid.uuid4().hex[:10]}")
    db.add(t)
    await db.flush()
    await default_branch(db, t.id)
    await db.commit()
    return t


async def _user(db, tenant, role="owner", email=None):
    u = User(tenant_id=tenant.id, email=email or f"{role}-{uuid.uuid4().hex[:6]}@x.co",
             password_hash=hash_password(PW), role=role)
    db.add(u)
    await db.commit()
    return u


def _auth(u, extra=None):
    token = create_access_token(u.id, u.tenant_id, u.role, u.token_version)
    return {"Authorization": f"Bearer {token}", **(extra or {})}


async def _login(client, email, headers=None):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": PW}, headers=headers or WEB)


async def _setup(db):
    stonic = await _tenant(db, "Stonic")
    admin = await _user(db, stonic, "owner", ADMIN)
    shop = await _tenant(db, "Al Noor Wholesale")
    owner = await _user(db, shop, "owner", "owner@alnoor.sa")
    rep = await _user(db, shop, "salesman", "rep@alnoor.sa")
    return admin, shop, owner, rep


# --- site switches ------------------------------------------------------------------------

async def test_closing_sign_in_locks_out_everyone_but_stonic(db, client):
    admin, shop, owner, rep = await _setup(db)
    assert (await client.get("/api/v1/site")).json()["sign_in_enabled"] is True

    r = await client.put("/api/v1/platform/settings", headers=_auth(admin),
                         json={"sign_in_enabled": False, "closed_message": "Back on 1 November."})
    assert r.status_code == 200 and r.json()["settings"]["sign_in_enabled"] is False
    assert r.json()["admin_emails"] == [ADMIN]

    public = (await client.get("/api/v1/site")).json()
    assert public == {"sign_in_enabled": False, "sign_up_enabled": False, "read_only": False,
                      "closed_message": "Back on 1 November.", "read_only_message": None,
                      "banner_text": None, "banner_tone": "info"}

    r = await _login(client, owner.email)
    assert r.status_code == 403 and r.json()["detail"] == "Back on 1 November."
    # someone already signed in is signed out on their next request
    r = await client.get("/api/v1/auth/me", headers=_auth(owner))
    assert r.status_code == 401 and r.json()["detail"] == "Back on 1 November."
    # sign-up is closed too while sign-in is
    r = await client.post("/api/v1/auth/register",
                          json={"tenant_name": "New Co", "email": "new@co.sa", "password": "longenough"})
    assert r.status_code == 403
    # Stonic still gets in
    assert (await _login(client, ADMIN)).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=_auth(admin))).status_code == 200

    reasons = [e.reason for e in await db.scalars(select(LoginEvent).order_by(LoginEvent.created_at))]
    assert reasons == ["sign_in_closed", "ok"]

    await client.put("/api/v1/platform/settings", headers=_auth(admin), json={"sign_in_enabled": True})
    assert (await _login(client, owner.email)).status_code == 200


async def test_sign_up_switch_and_banner(db, client):
    admin, *_ = await _setup(db)
    r = await client.put("/api/v1/platform/settings", headers=_auth(admin), json={
        "sign_up_enabled": False, "banner_text": "  New: Odoo sync is live  ", "banner_tone": "warning",
    })
    assert r.status_code == 200
    public = (await client.get("/api/v1/site")).json()
    assert public["sign_in_enabled"] is True and public["sign_up_enabled"] is False
    assert public["banner_text"] == "New: Odoo sync is live" and public["banner_tone"] == "warning"
    r = await client.post("/api/v1/auth/register",
                          json={"tenant_name": "New Co", "email": "new@co.sa", "password": "longenough"})
    assert r.status_code == 403 and r.json()["detail"] == site.SIGN_UP_CLOSED

    bad = await client.put("/api/v1/platform/settings", headers=_auth(admin), json={"banner_tone": "loud"})
    assert bad.status_code == 422
    audit = list(await db.scalars(select(AdminAuditLog)))
    assert [a.action for a in audit] == ["site.settings"]
    assert audit[0].detail["sign_up_enabled"] == {"from": True, "to": False}


async def test_read_only_mode_blocks_changes_but_not_reading(db, client):
    admin, shop, owner, rep = await _setup(db)
    await client.put("/api/v1/platform/settings", headers=_auth(admin), json={"read_only": True})
    assert (await client.get("/api/v1/customers", headers=_auth(owner))).status_code == 200
    r = await client.post("/api/v1/customers", headers=_auth(owner), json={"name": "Shop", "whatsapp_number": "+966500000009"})
    assert r.status_code == 503 and "read-only" in r.json()["detail"]
    # Stonic can still change things
    r = await client.post("/api/v1/customers", headers=_auth(admin), json={"name": "Shop", "whatsapp_number": "+966500000009"})
    assert r.status_code == 201


async def test_switches_do_nothing_without_a_stonic_admin(db, client, monkeypatch):
    admin, shop, owner, rep = await _setup(db)
    await client.put("/api/v1/platform/settings", headers=_auth(admin), json={"sign_in_enabled": False})
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", "")
    site.invalidate()
    assert (await _login(client, owner.email)).status_code == 200
    assert (await client.get("/api/v1/site")).json()["sign_in_enabled"] is True


async def test_only_stonic_sees_the_console(db, client):
    admin, shop, owner, rep = await _setup(db)
    for path in ("/settings", "/overview", "/businesses", "/people", "/system", "/audit", "/sign-ins"):
        assert (await client.get(f"/api/v1/platform{path}", headers=_auth(owner))).status_code == 404
        assert (await client.get(f"/api/v1/platform{path}", headers=_auth(admin))).status_code == 200, path


# --- businesses and people -------------------------------------------------------------------

async def test_suspending_a_business(db, client):
    admin, shop, owner, rep = await _setup(db)
    r = await client.post(f"/api/v1/platform/businesses/{shop.id}/suspend", headers=_auth(admin),
                          json={"reason": "Invoice unpaid for 60 days"})
    assert r.status_code == 200 and r.json()["suspended_reason"] == "Invoice unpaid for 60 days"
    assert (await _login(client, rep.email)).status_code == 403
    assert (await client.get("/api/v1/auth/me", headers=_auth(owner))).status_code == 401
    # Stonic can't suspend itself
    r = await client.post(f"/api/v1/platform/businesses/{admin.tenant_id}/suspend", headers=_auth(admin),
                          json={"reason": "oops"})
    assert r.status_code == 409

    rows = (await client.get("/api/v1/platform/businesses", headers=_auth(admin))).json()
    row = next(b for b in rows if b["id"] == str(shop.id))
    assert row["suspended_at"] and row["people"] == 2 and row["owner_email"] == "owner@alnoor.sa"

    r = await client.post(f"/api/v1/platform/businesses/{shop.id}/reactivate", headers=_auth(admin))
    assert r.status_code == 200 and r.json()["suspended_at"] is None
    assert (await _login(client, rep.email)).status_code == 200
    detail = (await client.get(f"/api/v1/platform/businesses/{shop.id}", headers=_auth(admin))).json()
    assert [p["email"] for p in detail["people"]] == ["owner@alnoor.sa", "rep@alnoor.sa"]
    assert detail["branches"][0]["name"] == "Main branch" and detail["erp"] is None
    assert [s["reason"] for s in detail["sign_ins"]][:2] == ["ok", "suspended"]


async def test_managing_people(db, client):
    admin, shop, owner, rep = await _setup(db)
    rep_token = _auth(rep)
    r = await client.get("/api/v1/platform/people", headers=_auth(admin), params={"q": "alnoor"})
    assert {p["email"] for p in r.json()} == {"owner@alnoor.sa", "rep@alnoor.sa"}
    assert all(p["business"] == "Al Noor Wholesale" for p in r.json())

    # sign out everywhere: old tokens stop working, a fresh sign-in works
    r = await client.post(f"/api/v1/platform/people/{rep.id}/sign-out", headers=_auth(admin))
    assert r.status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=rep_token)).status_code == 401
    assert (await _login(client, rep.email)).status_code == 200

    # a new password ends the old sessions too
    await db.refresh(rep)
    token = _auth(rep)
    r = await client.post(f"/api/v1/platform/people/{rep.id}/password", headers=_auth(admin), json={"password": "new-pass-99"})
    assert r.status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=token)).status_code == 401
    r = await client.post("/api/v1/auth/login", json={"email": rep.email, "password": "new-pass-99"})
    assert r.status_code == 200

    # switch off and back on
    r = await client.patch(f"/api/v1/platform/people/{rep.id}", headers=_auth(admin), json={"is_active": False})
    assert r.json()["is_active"] is False
    assert (await _login(client, rep.email)).status_code == 401  # wrong password now, still recorded
    r = await client.post("/api/v1/auth/login", json={"email": rep.email, "password": "new-pass-99"})
    assert r.status_code == 403
    await client.patch(f"/api/v1/platform/people/{rep.id}", headers=_auth(admin), json={"is_active": True, "role": "admin"})
    await db.refresh(rep)
    assert rep.is_active and rep.role == "admin" and rep.branch_id is None

    # the only owner stays an owner and stays on
    r = await client.patch(f"/api/v1/platform/people/{owner.id}", headers=_auth(admin), json={"role": "viewer"})
    assert r.status_code == 409
    r = await client.patch(f"/api/v1/platform/people/{owner.id}", headers=_auth(admin), json={"is_active": False})
    assert r.status_code == 409
    r = await client.patch(f"/api/v1/platform/people/{admin.id}", headers=_auth(admin), json={"is_active": False})
    assert r.status_code == 409
    assert (await client.patch(f"/api/v1/platform/people/{rep.id}", headers=_auth(admin), json={"role": "demo"})).status_code == 422

    actions = [a.action for a in await db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.created_at))]
    assert actions == ["person.sign_out", "person.password", "person.update", "person.update"]
    audit = (await client.get("/api/v1/platform/audit", headers=_auth(admin))).json()
    assert audit[0]["actor_email"] == ADMIN and len(audit) == 4
    failed = (await client.get("/api/v1/platform/sign-ins", headers=_auth(admin), params={"failed": True})).json()
    assert {f["reason"] for f in failed} == {"wrong_password", "inactive"}


# --- analytics --------------------------------------------------------------------------------

async def test_usage_is_tracked_per_client(db, client):
    admin, shop, owner, rep = await _setup(db)
    await client.get("/api/v1/auth/me", headers=_auth(owner, WEB))
    await client.get("/api/v1/auth/me", headers=_auth(owner, WEB))
    await client.get("/api/v1/auth/me", headers=_auth(rep, MOBILE))
    await client.get("/api/v1/auth/me", headers=_auth(rep, {"User-Agent": "okhttp/4.12.0"}))
    await client.get("/api/v1/auth/me", headers=_auth(owner, {"User-Agent": "Mozilla/5.0"}))
    rows = sorted((r.client, r.user_id == owner.id) for r in await db.scalars(select(UserActivity)))
    assert rows == [("mobile", False), ("web", True)]
    await db.refresh(owner)
    assert owner.last_seen_at is not None

    await _login(client, owner.email)
    await _login(client, rep.email, MOBILE)
    db.add(Order(tenant_id=shop.id, branch_id=(await default_branch(db, shop.id)).id, order_number="ORD-1",
                 status="confirmed", currency="SAR", total_amount=Decimal("250.00")))
    await db.commit()

    r = await client.get("/api/v1/platform/overview", headers=_auth(admin), params={"days": 7})
    data = r.json()
    p = data["period"]
    # the owner on the web, the rep on the app; Stonic calling from a script counts as neither
    assert (p["web_people"], p["mobile_people"], p["active_people"], p["sign_ins"], p["orders"]) == (1, 1, 3, 2, 1)
    assert p["order_value"] == [{"currency": "SAR", "amount": "250.00"}]
    assert len(data["series"]) == 7 and data["series"][-1]["mobile"] == 1 and data["series"][-1]["orders"] == 1
    assert data["totals"]["businesses"] == 2 and data["totals"]["online_now"] >= 2
    assert data["top_businesses"][0]["name"] == "Al Noor Wholesale"
    assert (await client.get("/api/v1/platform/overview", headers=_auth(admin), params={"days": 5})).status_code == 422


# --- system health ------------------------------------------------------------------------------

async def test_system_health_and_jobs(db, client):
    admin, shop, owner, rep = await _setup(db)
    job = Job(tenant_id=shop.id, kind="erp.push", payload={}, status="failed", attempts=8, max_attempts=8,
              last_error="OdooUnavailable: timed out", finished_at=datetime.now(timezone.utc))
    db.add(job)
    await db.commit()
    data = (await client.get("/api/v1/platform/system", headers=_auth(admin))).json()
    assert data["database"]["ok"] is True
    assert data["jobs"]["failed"][0]["business"] == "Al Noor Wholesale"
    assert next(k for k in data["jobs"]["kinds"] if k["kind"] == "erp.push")["failed"] == 1
    config = {c["key"]: c["ok"] for c in data["config"]}
    assert config["PLATFORM_ADMIN_EMAILS"] is True and "SECRETS_KEY" in config
    assert all("value" not in c for c in data["config"])

    r = await client.post(f"/api/v1/platform/jobs/{job.id}/retry", headers=_auth(admin))
    assert r.json()["status"] == "queued"
    await db.refresh(job)
    assert job.attempts == 0
    assert (await client.post(f"/api/v1/platform/jobs/{job.id}/retry", headers=_auth(admin))).status_code == 409
    r = await client.post(f"/api/v1/platform/jobs/{job.id}/discard", headers=_auth(admin))
    assert r.json()["status"] == "discarded"
    count = await db.scalar(select(func.count(AdminAuditLog.id)).where(AdminAuditLog.target_type == "job"))
    assert count == 2


async def test_cached_switches_expire(db, client, monkeypatch):
    """A change made by another server reaches this one within the cache time."""
    admin, shop, owner, rep = await _setup(db)
    assert (await site.effective(db))["sign_in_enabled"] is True
    row = await site._row(db)
    row.data = {"sign_in_enabled": False}
    await db.commit()
    assert (await site.effective(db))["sign_in_enabled"] is True  # still cached
    monkeypatch.setattr(site, "_CACHE_SECONDS", 0.0)
    assert (await site.effective(db))["sign_in_enabled"] is False