"""Branches: per-branch prices and stock, staff access, WhatsApp routing, and order updates."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest_asyncio
from sqlalchemy import func, select

from app.core.branches import default_branch
from app.core.security import create_access_token, hash_password
from app.db.models.branch import Branch
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.inventory import Inventory
from app.db.models.job import Job
from app.db.models.message import Message
from app.db.models.order import Order
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.models.zone import Zone
from app.db.session import get_session
from app.jobs import queue
from app.main import app
from app.modules.notifications import service as notifications
from app.modules.orders import service as orders
from app.modules.pricing import service as pricing
from app.schemas.order import OrderCreate, OrderItemIn
from app.schemas.pricing import PriceLineIn, PriceListCreate


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


async def _business(db):
    """A tenant with two branches; Jeddah has its own WhatsApp number."""
    t = Tenant(name="Al Rayyan Fresh", slug=f"t-{uuid.uuid4().hex[:10]}")
    db.add(t)
    await db.flush()
    riyadh = await default_branch(db, t.id)
    riyadh.name = "Riyadh"
    riyadh.whatsapp_phone_number_id, riyadh.whatsapp_access_token = f"PN-R-{t.id.hex[:6]}", "tok-r"
    jeddah = Branch(tenant_id=t.id, name="Jeddah", is_default=False, is_active=True, order_updates_enabled=True,
                    whatsapp_phone_number_id=f"PN-J-{t.id.hex[:6]}", whatsapp_access_token="tok-j")
    db.add(jeddah)
    await db.commit()
    return t, riyadh, jeddah


async def _user(db, t, role, branch=None, name=None):
    u = User(tenant_id=t.id, email=f"{role}-{uuid.uuid4().hex[:6]}@x.co", full_name=name, role=role,
             password_hash=hash_password("pw-123456"), branch_id=branch.id if branch else None)
    db.add(u)
    await db.commit()
    return u


def _auth(u, branch=None):
    h = {"Authorization": f"Bearer {create_access_token(u.id, u.tenant_id, u.role)}"}
    if branch is not None:
        h["X-Branch-Id"] = str(branch.id)
    return h


async def _prices(db, t, branch, price, qty):
    pl = await pricing.create_price_list(db, t.id, PriceListCreate(lines=[
        PriceLineIn(sku="TOM-5", unit_price=Decimal(price), quantity=qty, currency="SAR"),
    ]), branch_id=branch.id)
    await pricing.activate_price_list(db, t.id, pl.id)
    return pl


# --- prices and stock ---------------------------------------------------------------

async def test_each_branch_has_its_own_prices_and_stock(db):
    t, riyadh, jeddah = await _business(db)
    await _prices(db, t, riyadh, "35", 100)
    await _prices(db, t, jeddah, "38", 5)
    # activating a new Riyadh list leaves Jeddah untouched
    await _prices(db, t, riyadh, "34", 80)

    r = await pricing.get_current_price(db, t.id, "TOM-5", riyadh.id)
    j = await pricing.get_current_price(db, t.id, "TOM-5", jeddah.id)
    assert (r["unit_price"], r["quantity_on_hand"]) == (Decimal("34"), 80)
    assert (j["unit_price"], j["quantity_on_hand"]) == (Decimal("38"), 5)
    lists = await pricing.list_price_lists(db, t.id, jeddah.id)
    assert [pl.status for pl in lists] == ["active"]


async def test_orders_take_stock_from_their_own_branch(db):
    t, riyadh, jeddah = await _business(db)
    await _prices(db, t, riyadh, "35", 100)
    await _prices(db, t, jeddah, "38", 5)

    o = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=10)],
                                                        branch_id=jeddah.id))
    # Jeddah only has 5: held for review even though Riyadh has 100
    assert o.status == "requires_human_review" and o.branch_id == jeddah.id
    o2 = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=10)]))
    assert o2.status == "confirmed" and o2.branch_id == riyadh.id and o2.total_amount == Decimal("350")
    stock = dict((await db.execute(select(Inventory.branch_id, Inventory.quantity_on_hand))).all())
    assert stock == {riyadh.id: 90, jeddah.id: 5}


async def test_customer_orders_go_to_the_customers_branch(db):
    t, riyadh, jeddah = await _business(db)
    await _prices(db, t, jeddah, "38", 50)
    c = Customer(tenant_id=t.id, branch_id=jeddah.id, name="Al Balad", whatsapp_number="+966550000001")
    db.add(c)
    await db.commit()
    o = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=2)], customer_id=c.id))
    assert o.branch_id == jeddah.id and o.total_amount == Decimal("76")


# --- access ---------------------------------------------------------------------------

async def test_branch_staff_see_only_their_branch(db, client):
    t, riyadh, jeddah = await _business(db)
    await _prices(db, t, riyadh, "35", 100)
    await _prices(db, t, jeddah, "38", 100)
    r_order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=1)], branch_id=riyadh.id))
    j_order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=1)], branch_id=jeddah.id))
    dispatcher = await _user(db, t, "dispatcher", jeddah)
    owner = await _user(db, t, "owner")

    rows = (await client.get("/api/v1/orders", headers=_auth(dispatcher))).json()
    assert [r["id"] for r in rows] == [str(j_order.id)]
    # the header can't widen a branch user's access
    rows = (await client.get("/api/v1/orders", headers=_auth(dispatcher, riyadh))).json()
    assert [r["id"] for r in rows] == [str(j_order.id)]
    assert (await client.get(f"/api/v1/orders/{r_order.id}", headers=_auth(dispatcher))).status_code == 404
    r = await client.post(f"/api/v1/orders/{r_order.id}/transition", headers=_auth(dispatcher),
                          json={"to_status": "dispatched"})
    assert r.status_code == 404

    assert len((await client.get("/api/v1/orders", headers=_auth(owner))).json()) == 2
    rows = (await client.get("/api/v1/orders", headers=_auth(owner, riyadh))).json()
    assert [r["id"] for r in rows] == [str(r_order.id)]

    catalog = (await client.get("/api/v1/products/catalog", headers=_auth(owner))).json()
    assert catalog[0]["unit_price"] is None and (catalog[0]["price_min"], catalog[0]["price_max"]) == (35, 38)
    assert catalog[0]["stock"] == 198
    catalog = (await client.get("/api/v1/products/catalog", headers=_auth(dispatcher))).json()
    assert (catalog[0]["unit_price"], catalog[0]["stock"]) == (38, 99)


async def test_branch_header_from_another_business_is_rejected(db, client):
    t, riyadh, _ = await _business(db)
    other, other_branch, _ = await _business(db)
    owner = await _user(db, t, "owner")
    assert (await client.get("/api/v1/orders", headers=_auth(owner, other_branch))).status_code == 404


async def test_price_upload_needs_a_branch_when_looking_at_all(db, client):
    t, riyadh, jeddah = await _business(db)
    owner = await _user(db, t, "owner")
    body = {"lines": [{"sku": "TOM-5", "unit_price": "35", "quantity": 1, "currency": "SAR"}]}
    r = await client.post("/api/v1/pricing/price-lists", headers=_auth(owner), json=body)
    assert r.status_code == 422 and "Choose a branch" in r.json()["detail"]
    r = await client.post("/api/v1/pricing/price-lists", headers=_auth(owner, jeddah), json=body)
    assert r.status_code == 201 and r.json()["branch_id"] == str(jeddah.id)


async def test_customer_zone_must_match_branch(db, client):
    t, riyadh, jeddah = await _business(db)
    admin = await _user(db, t, "admin")
    zone = Zone(tenant_id=t.id, branch_id=jeddah.id, name="Jeddah Al Safa")
    db.add(zone)
    await db.commit()
    r = await client.post("/api/v1/customers", headers=_auth(admin), json={"name": "Corniche", "zone_id": str(zone.id)})
    assert r.status_code == 201 and r.json()["branch_id"] == str(jeddah.id)
    r = await client.post("/api/v1/customers", headers=_auth(admin),
                          json={"name": "Mismatch", "zone_id": str(zone.id), "branch_id": str(riyadh.id)})
    assert r.status_code == 422


async def test_branches_api(db, client):
    t, riyadh, jeddah = await _business(db)
    admin = await _user(db, t, "admin")
    driver = await _user(db, t, "driver", jeddah)

    r = await client.post("/api/v1/branches", headers=_auth(admin), json={
        "name": "Dammam", "whatsapp_phone_number_id": "PN-D", "whatsapp_access_token": "secret"})
    assert r.status_code == 201
    body = r.json()
    assert body["whatsapp_connected"] is True and "whatsapp_access_token" not in body
    dup = await client.post("/api/v1/branches", headers=_auth(admin),
                            json={"name": "Khobar", "whatsapp_phone_number_id": "PN-D"})
    assert dup.status_code == 409

    r = await client.patch(f"/api/v1/branches/{body['id']}", headers=_auth(admin), json={"is_default": True})
    assert r.json()["is_default"] is True
    await db.refresh(riyadh)
    assert riyadh.is_default is False
    r = await client.patch(f"/api/v1/branches/{body['id']}", headers=_auth(admin), json={"is_active": False})
    assert r.status_code == 422

    names = [b["name"] for b in (await client.get("/api/v1/branches", headers=_auth(driver))).json()]
    assert names == ["Jeddah"]
    me = (await client.get("/api/v1/auth/me", headers=_auth(driver))).json()
    assert me["branch_name"] == "Jeddah" and me["sees_all_branches"] is False
    assert (await client.post("/api/v1/branches", headers=_auth(driver), json={"name": "X"})).status_code == 403


async def test_staff_get_a_branch_and_admins_do_not(db, client):
    t, riyadh, jeddah = await _business(db)
    owner = await _user(db, t, "owner")
    r = await client.post("/api/v1/users", headers=_auth(owner), json={
        "email": "w@example.com", "password": "pw-12345678", "role": "warehouse", "branch_id": str(jeddah.id)})
    assert r.json()["branch_id"] == str(jeddah.id)
    r = await client.post("/api/v1/users", headers=_auth(owner), json={
        "email": "a@example.com", "password": "pw-12345678", "role": "admin", "branch_id": str(jeddah.id)})
    assert r.json()["branch_id"] is None
    r = await client.post("/api/v1/users", headers=_auth(owner), json={
        "email": "s@example.com", "password": "pw-12345678", "role": "salesman"})
    assert r.json()["branch_id"] == str(riyadh.id)  # default branch


# --- WhatsApp routing ---------------------------------------------------------------------

async def test_inbound_message_is_handled_by_the_branch_that_owns_the_number(db, monkeypatch):
    import app.channels.whatsapp.service as wa

    t, riyadh, jeddah = await _business(db)
    seen = {}

    async def _agent(db_, tenant_id, name, history, text, **kw):
        seen.update(kw)
        return {"reply": "أهلاً"}

    monkeypatch.setattr(wa, "run_agent", _agent)
    await wa.process_incoming(db, jeddah.whatsapp_phone_number_id, "966550000009", "كم سعر الطماطم؟", "wamid.J", None)

    assert seen == {"branch_id": jeddah.id, "customer_number": "966550000009"}
    conv = await db.scalar(select(Conversation))
    assert conv.branch_id == jeddah.id and conv.language == "ar"
    job = await db.scalar(select(Job).where(Job.kind == queue.WHATSAPP_SEND_TEXT))
    assert job.payload["branch_id"] == str(jeddah.id)


async def test_reply_is_sent_from_the_branch_number(db, monkeypatch):
    import app.channels.whatsapp.service as wa
    from app.jobs import handlers

    t, riyadh, jeddah = await _business(db)
    sent = []

    async def _post(branch, payload):
        sent.append((branch.whatsapp_phone_number_id, payload))
        return {}

    monkeypatch.setattr(wa, "_post_message", _post)
    await handlers.send_text(db, {"tenant_id": str(t.id), "branch_id": str(jeddah.id), "to": "9665", "body": "hi"})
    await handlers.send_text(db, {"tenant_id": str(t.id), "to": "9665", "body": "legacy"})  # queued before branches
    assert [n for n, _ in sent] == [jeddah.whatsapp_phone_number_id, riyadh.whatsapp_phone_number_id]


async def test_agent_order_links_the_customer_and_branch(db):
    from app.ai import tools

    t, riyadh, jeddah = await _business(db)
    await _prices(db, t, jeddah, "38", 50)
    c = Customer(tenant_id=t.id, branch_id=jeddah.id, name="Al Balad", whatsapp_number="+966550000001")
    db.add(c)
    await db.commit()
    ctx = tools.ToolContext(tenant_id=t.id, branch_id=jeddah.id, customer_number="966550000001")
    stock = await tools.dispatch(db, ctx, "get_price_and_stock", {"sku": "TOM-5"})
    assert stock["unit_price"] == 38 and stock["quantity_on_hand"] == 50
    r = await tools.dispatch(db, ctx, "place_order", {"items": [{"sku": "TOM-5", "quantity": 3}]})
    o = await db.scalar(select(Order).where(Order.order_number == r["order_number"]))
    assert o.branch_id == jeddah.id and o.customer_id == c.id and o.whatsapp_number == "966550000001"


# --- order updates ----------------------------------------------------------------------

async def _order_with_chat(db, t, branch, *, language="en", last_in=timedelta(hours=1)):
    await _prices(db, t, branch, "35", 100)
    o = await orders.create_order(db, t.id, OrderCreate(
        items=[OrderItemIn(sku="TOM-5", quantity=4)], branch_id=branch.id,
        customer_name="Khalid", whatsapp_number="966500000777"))
    conv = Conversation(tenant_id=t.id, branch_id=branch.id, customer_number="966500000777",
                        language=language, status="active")
    db.add(conv)
    await db.flush()
    db.add(Message(tenant_id=t.id, conversation_id=conv.id, direction="in", sender="customer",
                   content="hello", created_at=datetime.now(timezone.utc) - last_in))
    await db.commit()
    return o


def _capture(monkeypatch):
    import app.channels.whatsapp.service as wa

    sent = []

    async def _text(branch, to, body):
        sent.append(("text", to, body))

    async def _template(branch, to, name, language, params):
        sent.append(("template", name, language, params))

    monkeypatch.setattr(wa, "send_text", _text)
    monkeypatch.setattr(wa, "send_template", _template)
    return sent


async def test_dispatch_update_inside_the_24_hour_window(db, monkeypatch):
    t, riyadh, _ = await _business(db)
    o = await _order_with_chat(db, t, riyadh, language="ar")
    sent = _capture(monkeypatch)

    await orders.transition_order(db, t.id, o.id, "dispatched")
    jobs = list(await db.scalars(select(Job).where(Job.kind == queue.WHATSAPP_ORDER_UPDATE)))
    assert len(jobs) == 1 and jobs[0].dedupe_key == f"order-update:{o.id}:dispatched"
    assert await notifications.queue_order_update(db, o, "dispatched") is False  # never twice

    assert await notifications.send_order_update(db, jobs[0].payload) == "text"
    kind, to, body = sent[0]
    assert kind == "text" and to == "966500000777" and o.order_number in body and "في الطريق" in body
    logged = await db.scalar(select(Message).where(Message.sender == "system"))
    assert logged.content == body


async def test_update_outside_the_window_uses_the_template(db, monkeypatch):
    t, riyadh, _ = await _business(db)
    riyadh.whatsapp_update_template = "order_update"
    o = await _order_with_chat(db, t, riyadh, last_in=timedelta(hours=30))
    sent = _capture(monkeypatch)
    result = await notifications.send_order_update(db, {"order_id": str(o.id), "event": "delivered"})
    assert result == "template"
    assert sent == [("template", "order_update", "en", ["Khalid", o.order_number, "it has been delivered"])]


async def test_update_outside_the_window_without_template_is_skipped(db, monkeypatch):
    t, riyadh, _ = await _business(db)
    o = await _order_with_chat(db, t, riyadh, last_in=timedelta(days=3))
    sent = _capture(monkeypatch)
    result = await notifications.send_order_update(db, {"order_id": str(o.id), "event": "delivered"})
    assert result.startswith("skipped") and sent == []
    assert await db.scalar(select(func.count(Message.id)).where(Message.sender == "system")) == 0


async def test_updates_can_be_switched_off_per_branch(db, monkeypatch):
    t, riyadh, _ = await _business(db)
    riyadh.order_updates_enabled = False
    o = await _order_with_chat(db, t, riyadh)
    sent = _capture(monkeypatch)
    assert (await notifications.send_order_update(db, {"order_id": str(o.id), "event": "dispatched"})).startswith("skipped")
    assert sent == []


async def test_partly_approved_held_order_tells_the_customer_what_was_supplied(db, monkeypatch):
    t, riyadh, _ = await _business(db)
    await _prices(db, t, riyadh, "35", 3)
    o = await orders.create_order(db, t.id, OrderCreate(
        items=[OrderItemIn(sku="TOM-5", quantity=5)], customer_name="Khalid", whatsapp_number="966500000777"))
    conv = Conversation(tenant_id=t.id, branch_id=riyadh.id, customer_number="966500000777", status="active")
    db.add(conv)
    await db.flush()
    db.add(Message(tenant_id=t.id, conversation_id=conv.id, direction="in", sender="customer", content="hi"))
    await db.commit()
    esc = (await orders.list_escalations(db, t.id))[0]
    await orders.resolve_escalation(db, t.id, esc.id, approve=True)

    job = await db.scalar(select(Job).where(Job.kind == queue.WHATSAPP_ORDER_UPDATE))
    assert job.payload["event"] == "approved"
    sent = _capture(monkeypatch)
    await notifications.send_order_update(db, job.payload)
    body = sent[0][2]
    assert "is confirmed" in body and "SAR 105" in body and "3 of 5" in body


async def test_no_update_without_a_customer_number(db):
    t, riyadh, _ = await _business(db)
    await _prices(db, t, riyadh, "35", 10)
    o = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=1)]))
    await orders.transition_order(db, t.id, o.id, "dispatched")
    assert await db.scalar(select(func.count(Job.id)).where(Job.kind == queue.WHATSAPP_ORDER_UPDATE)) == 0


async def test_approving_a_held_order_with_nothing_in_stock_cancels_it(db):
    t, riyadh, _ = await _business(db)
    await _prices(db, t, riyadh, "35", 0)
    o = await orders.create_order(db, t.id, OrderCreate(
        items=[OrderItemIn(sku="TOM-5", quantity=5)], whatsapp_number="966500000777"))
    esc = (await orders.list_escalations(db, t.id))[0]
    esc = await orders.resolve_escalation(db, t.id, esc.id, approve=True)
    await db.refresh(o)
    assert o.status == "cancelled" and esc.resolution == "rejected" and "nothing was in stock" in esc.resolution_note
    job = await db.scalar(select(Job).where(Job.kind == queue.WHATSAPP_ORDER_UPDATE))
    assert job.payload["event"] == "rejected"