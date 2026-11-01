"""The Stonic Console: admin accounts, site switches, suspension, people, analytics, system health and the audit log."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.branches import default_branch
from app.core.security import create_access_token, create_admin_token, hash_password
from app.db.models.job import Job
from app.db.models.order import Order
from app.db.models.platform import AdminAuditLog, LoginEvent, PlatformAdmin, UserActivity
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.session import get_session
from app.main import app
from app.modules.platform import admins, site

ADMIN = "ops@stonic-hq.com"
ADMIN_PW = "console-pass-1"
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
def _fresh_switches():
    site.invalidate()
    yield
    site.invalidate()


async def _admin(db, email=ADMIN, name="Ops"):
    a = PlatformAdmin(email=email, password_hash=hash_password(ADMIN_PW), full_name=name)
    db.add(a)
    await db.commit()
    site.invalidate()
    return a


def _console(a):
    return {"Authorization": f"Bearer {create_admin_token(a.id, a.token_version)}"}


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
    admin = await _admin(db)
    shop = await _tenant(db, "Al Noor Wholesale")
    owner = await _user(db, shop, "owner", "owner@alnoor.sa")
    rep = await _user(db, shop, "salesman", "rep@alnoor.sa")
    return admin, shop, owner, rep


# --- site switches ------------------------------------------------------------------------

async def test_closing_sign_in_locks_out_every_business_user(db, client):
    admin, shop, owner, rep = await _setup(db)
    assert (await client.get("/api/v1/site")).json()["sign_in_enabled"] is True

    r = await client.put("/api/v1/platform/settings", headers=_console(admin),
                         json={"sign_in_enabled": False, "closed_message": "Back on 1 November."})
    assert r.status_code == 200 and r.json()["settings"]["sign_in_enabled"] is False
    assert r.json()["admins"] == [ADMIN]

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
    # the console still works: admins are not business users
    r = await client.post("/api/v1/platform/auth/login", json={"email": ADMIN, "password": ADMIN_PW})
    assert r.status_code == 200
    assert (await client.get("/api/v1/platform/overview", headers=_console(admin))).status_code == 200

    reasons = [e.reason for e in await db.scalars(select(LoginEvent).order_by(LoginEvent.created_at))]
    assert reasons == ["sign_in_closed"]

    await client.put("/api/v1/platform/settings", headers=_console(admin), json={"sign_in_enabled": True})
    assert (await _login(client, owner.email)).status_code == 200


async def test_sign_up_switch_and_banner(db, client):
    admin, *_ = await _setup(db)
    r = await client.put("/api/v1/platform/settings", headers=_console(admin), json={
        "sign_up_enabled": False, "banner_text": "  New: Odoo sync is live  ", "banner_tone": "warning",
    })
    assert r.status_code == 200
    public = (await client.get("/api/v1/site")).json()
    assert public["sign_in_enabled"] is True and public["sign_up_enabled"] is False
    assert public["banner_text"] == "New: Odoo sync is live" and public["banner_tone"] == "warning"
    r = await client.post("/api/v1/auth/register",
                          json={"tenant_name": "New Co", "email": "new@co.sa", "password": "longenough"})
    assert r.status_code == 403 and r.json()["detail"] == site.SIGN_UP_CLOSED

    bad = await client.put("/api/v1/platform/settings", headers=_console(admin), json={"banner_tone": "loud"})
    assert bad.status_code == 422
    audit = list(await db.scalars(select(AdminAuditLog)))
    assert [a.action for a in audit] == ["site.settings"]
    assert audit[0].detail["sign_up_enabled"] == {"from": True, "to": False}


async def test_read_only_mode_blocks_changes_but_not_reading(db, client):
    admin, shop, owner, rep = await _setup(db)
    await client.put("/api/v1/platform/settings", headers=_console(admin), json={"read_only": True})
    assert (await client.get("/api/v1/customers", headers=_auth(owner))).status_code == 200
    r = await client.post("/api/v1/customers", headers=_auth(owner), json={"name": "Shop", "whatsapp_number": "+966500000009"})
    assert r.status_code == 503 and "read-only" in r.json()["detail"]
    # the console can still change things
    r = await client.put("/api/v1/platform/settings", headers=_console(admin), json={"read_only": False})
    assert r.status_code == 200
    r = await client.post("/api/v1/customers", headers=_auth(owner), json={"name": "Shop", "whatsapp_number": "+966500000009"})
    assert r.status_code == 201


async def test_switches_do_nothing_without_an_active_admin(db, client):
    """Nobody could switch the site back on, so it stays open."""
    admin, shop, owner, rep = await _setup(db)
    await client.put("/api/v1/platform/settings", headers=_console(admin), json={"sign_in_enabled": False})
    assert (await _login(client, owner.email)).status_code == 403
    admin.is_active = False
    await db.commit()
    site.invalidate()
    assert (await _login(client, owner.email)).status_code == 200
    assert (await client.get("/api/v1/site")).json()["sign_in_enabled"] is True


async def test_console_and_business_sessions_are_kept_apart(db, client):
    admin, shop, owner, rep = await _setup(db)
    paths = ("/settings", "/overview", "/businesses", "/people", "/system", "/audit", "/sign-ins", "/admins",
             "/auth/me", "/tenants")
    for path in paths:
        assert (await client.get(f"/api/v1/platform{path}")).status_code == 401, path
        assert (await client.get(f"/api/v1/platform{path}", headers=_auth(owner))).status_code == 401, path
        assert (await client.get(f"/api/v1/platform{path}", headers=_console(admin))).status_code == 200, path
    # an admin token is no use on the business side
    assert (await client.get("/api/v1/auth/me", headers=_console(admin))).status_code == 401
    assert (await client.get("/api/v1/customers", headers=_console(admin))).status_code == 401
    # an admin's email does not sign in to the business app
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN, "password": ADMIN_PW})
    assert r.status_code == 401


# --- businesses and people -------------------------------------------------------------------

async def test_suspending_a_business(db, client):
    admin, shop, owner, rep = await _setup(db)
    r = await client.post(f"/api/v1/platform/businesses/{shop.id}/suspend", headers=_console(admin),
                          json={"reason": "Invoice unpaid for 60 days"})
    assert r.status_code == 200 and r.json()["suspended_reason"] == "Invoice unpaid for 60 days"
    assert (await _login(client, rep.email)).status_code == 403
    assert (await client.get("/api/v1/auth/me", headers=_auth(owner))).status_code == 401
    r = await client.post(f"/api/v1/platform/businesses/{uuid.uuid4()}/suspend", headers=_console(admin),
                          json={"reason": "oops"})
    assert r.status_code == 404

    rows = (await client.get("/api/v1/platform/businesses", headers=_console(admin))).json()
    row = next(b for b in rows if b["id"] == str(shop.id))
    assert row["suspended_at"] and row["people"] == 2 and row["owner_email"] == "owner@alnoor.sa"

    r = await client.post(f"/api/v1/platform/businesses/{shop.id}/reactivate", headers=_console(admin))
    assert r.status_code == 200 and r.json()["suspended_at"] is None
    assert (await _login(client, rep.email)).status_code == 200
    detail = (await client.get(f"/api/v1/platform/businesses/{shop.id}", headers=_console(admin))).json()
    assert [p["email"] for p in detail["people"]] == ["owner@alnoor.sa", "rep@alnoor.sa"]
    assert detail["branches"][0]["name"] == "Main branch" and detail["erp"] is None
    assert [s["reason"] for s in detail["sign_ins"]][:2] == ["ok", "suspended"]


async def test_managing_people(db, client):
    admin, shop, owner, rep = await _setup(db)
    rep_token = _auth(rep)
    r = await client.get("/api/v1/platform/people", headers=_console(admin), params={"q": "alnoor"})
    assert {p["email"] for p in r.json()} == {"owner@alnoor.sa", "rep@alnoor.sa"}
    assert all(p["business"] == "Al Noor Wholesale" for p in r.json())

    # sign out everywhere: old tokens stop working, a fresh sign-in works
    r = await client.post(f"/api/v1/platform/people/{rep.id}/sign-out", headers=_console(admin))
    assert r.status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=rep_token)).status_code == 401
    assert (await _login(client, rep.email)).status_code == 200

    # a new password ends the old sessions too
    await db.refresh(rep)
    token = _auth(rep)
    r = await client.post(f"/api/v1/platform/people/{rep.id}/password", headers=_console(admin), json={"password": "new-pass-99"})
    assert r.status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=token)).status_code == 401
    r = await client.post("/api/v1/auth/login", json={"email": rep.email, "password": "new-pass-99"})
    assert r.status_code == 200

    # switch off and back on
    r = await client.patch(f"/api/v1/platform/people/{rep.id}", headers=_console(admin), json={"is_active": False})
    assert r.json()["is_active"] is False
    assert (await _login(client, rep.email)).status_code == 401  # wrong password now, still recorded
    r = await client.post("/api/v1/auth/login", json={"email": rep.email, "password": "new-pass-99"})
    assert r.status_code == 403
    await client.patch(f"/api/v1/platform/people/{rep.id}", headers=_console(admin), json={"is_active": True, "role": "admin"})
    await db.refresh(rep)
    assert rep.is_active and rep.role == "admin" and rep.branch_id is None

    # the only owner stays an owner and stays on
    r = await client.patch(f"/api/v1/platform/people/{owner.id}", headers=_console(admin), json={"role": "viewer"})
    assert r.status_code == 409
    r = await client.patch(f"/api/v1/platform/people/{owner.id}", headers=_console(admin), json={"is_active": False})
    assert r.status_code == 409
    assert (await client.patch(f"/api/v1/platform/people/{rep.id}", headers=_console(admin), json={"role": "demo"})).status_code == 422

    actions = [a.action for a in await db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.created_at))]
    assert actions == ["person.sign_out", "person.password", "person.update", "person.update"]
    audit = (await client.get("/api/v1/platform/audit", headers=_console(admin))).json()
    assert audit[0]["actor_email"] == ADMIN and len(audit) == 4
    failed = (await client.get("/api/v1/platform/sign-ins", headers=_console(admin), params={"failed": True})).json()
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

    r = await client.get("/api/v1/platform/overview", headers=_console(admin), params={"days": 7})
    data = r.json()
    p = data["period"]
    # the owner on the web, the rep on the app; console admins are not counted
    assert (p["web_people"], p["mobile_people"], p["active_people"], p["sign_ins"], p["orders"]) == (1, 1, 2, 2, 1)
    assert p["order_value"] == [{"currency": "SAR", "amount": "250.00"}]
    assert len(data["series"]) == 7 and data["series"][-1]["mobile"] == 1 and data["series"][-1]["orders"] == 1
    assert data["totals"]["businesses"] == 1 and data["totals"]["online_now"] >= 2
    assert data["top_businesses"][0]["name"] == "Al Noor Wholesale"
    assert (await client.get("/api/v1/platform/overview", headers=_console(admin), params={"days": 5})).status_code == 422


# --- system health ------------------------------------------------------------------------------

async def test_system_health_and_jobs(db, client):
    admin, shop, owner, rep = await _setup(db)
    job = Job(tenant_id=shop.id, kind="erp.push", payload={}, status="failed", attempts=8, max_attempts=8,
              last_error="OdooUnavailable: timed out", finished_at=datetime.now(timezone.utc))
    db.add(job)
    await db.commit()
    data = (await client.get("/api/v1/platform/system", headers=_console(admin))).json()
    assert data["database"]["ok"] is True
    assert data["jobs"]["failed"][0]["business"] == "Al Noor Wholesale"
    assert next(k for k in data["jobs"]["kinds"] if k["kind"] == "erp.push")["failed"] == 1
    config = {c["key"]: c["ok"] for c in data["config"]}
    assert "PLATFORM_ADMIN_EMAILS" not in config and "SECRETS_KEY" in config
    assert data["server"]["admins"] == 1
    assert all("value" not in c for c in data["config"])

    r = await client.post(f"/api/v1/platform/jobs/{job.id}/retry", headers=_console(admin))
    assert r.json()["status"] == "queued"
    await db.refresh(job)
    assert job.attempts == 0
    assert (await client.post(f"/api/v1/platform/jobs/{job.id}/retry", headers=_console(admin))).status_code == 409
    r = await client.post(f"/api/v1/platform/jobs/{job.id}/discard", headers=_console(admin))
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


# --- admin accounts -----------------------------------------------------------------------------

async def test_admin_sign_in(db, client):
    admin = await _admin(db, "boss@stonic.site", "Boss")
    r = await client.post("/api/v1/platform/auth/login", json={"email": " Boss@Stonic.SITE ", "password": ADMIN_PW})
    assert r.status_code == 200 and r.json()["admin"]["email"] == "boss@stonic.site"
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await client.get("/api/v1/platform/auth/me", headers=h)).json()
    assert me["full_name"] == "Boss" and me["last_login_at"]

    for email, pw in (("boss@stonic.site", "wrong-password"), ("nobody@stonic.site", ADMIN_PW)):
        r = await client.post("/api/v1/platform/auth/login", json={"email": email, "password": pw})
        assert r.status_code == 401 and r.json()["detail"] == "Wrong email or password"
    admin.is_active = False
    await db.commit()
    r = await client.post("/api/v1/platform/auth/login", json={"email": "boss@stonic.site", "password": ADMIN_PW})
    assert r.status_code == 401
    assert (await client.get("/api/v1/platform/auth/me", headers=h)).status_code == 401

    rows = await db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.created_at))
    log = [(a.action, a.detail.get("reason")) for a in rows]
    assert log == [("admin.sign_in", None), ("admin.sign_in_failed", "wrong password"),
                   ("admin.sign_in_failed", "unknown email"), ("admin.sign_in_failed", "switched off")]
    # business sign-ins are a separate log
    assert await db.scalar(select(func.count(LoginEvent.id))) == 0


async def test_managing_admins(db, client):
    me_ = await _admin(db)
    h = _console(me_)
    r = await client.post("/api/v1/platform/admins", headers=h,
                          json={"email": "New@Stonic.site", "password": "another-pass-1", "full_name": "New"})
    assert r.status_code == 201 and r.json()["email"] == "new@stonic.site"
    new_id = r.json()["id"]
    assert (await client.post("/api/v1/platform/admins", headers=h,
                              json={"email": "new@stonic.site", "password": "another-pass-1"})).status_code == 409
    assert (await client.post("/api/v1/platform/admins", headers=h,
                              json={"email": "x@stonic.site", "password": "short"})).status_code == 422
    listed = (await client.get("/api/v1/platform/admins", headers=h)).json()
    assert [a["email"] for a in listed] == [ADMIN, "new@stonic.site"]

    # the new admin signs in, then is switched off and loses the session
    r = await client.post("/api/v1/platform/auth/login", json={"email": "new@stonic.site", "password": "another-pass-1"})
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get("/api/v1/platform/overview", headers=other)).status_code == 200
    r = await client.patch(f"/api/v1/platform/admins/{new_id}", headers=h, json={"is_active": False, "full_name": "Newer"})
    assert r.json()["is_active"] is False and r.json()["full_name"] == "Newer"
    assert (await client.get("/api/v1/platform/overview", headers=other)).status_code == 401
    # you can't switch yourself off
    r = await client.patch(f"/api/v1/platform/admins/{me_.id}", headers=h, json={"is_active": False})
    assert r.status_code == 409

    # someone else's password: no current password needed, no token back
    r = await client.post(f"/api/v1/platform/admins/{new_id}/password", headers=h, json={"password": "reset-pass-123"})
    assert r.status_code == 200 and r.json()["access_token"] is None
    # your own: the current one is needed, and you get a fresh token
    r = await client.post(f"/api/v1/platform/admins/{me_.id}/password", headers=h, json={"password": "my-new-pass-1"})
    assert r.status_code == 422
    r = await client.post(f"/api/v1/platform/admins/{me_.id}/password", headers=h,
                          json={"password": "my-new-pass-1", "current_password": ADMIN_PW})
    assert r.status_code == 200
    assert (await client.get("/api/v1/platform/auth/me", headers=h)).status_code == 401  # old session ended
    fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get("/api/v1/platform/auth/me", headers=fresh)).status_code == 200

    actions = [a.action for a in await db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.created_at))]
    assert actions == ["admin.create", "admin.sign_in", "admin.update", "admin.password", "admin.password"]
    audit = (await client.get("/api/v1/platform/audit", headers=fresh)).json()
    assert audit[0]["actor_email"] == ADMIN


async def test_command_line_admin(db):
    a, created = await admins.ensure_admin(db, email=" Owner@Stonic.site", password="first-pass-123", full_name="Owner")
    assert created and a.email == "owner@stonic.site" and a.is_active
    version = a.token_version
    a.is_active = False
    await db.commit()
    a, created = await admins.ensure_admin(db, email="owner@stonic.site", password="second-pass-123", full_name=None)
    assert not created and a.is_active and a.token_version == version + 1 and a.full_name == "Owner"
    assert (await admins.authenticate(db, "owner@stonic.site", "second-pass-123"))[0].id == a.id
    with pytest.raises(HTTPException):
        await admins.ensure_admin(db, email="x@stonic.site", password="short", full_name=None)