"""Order intelligence: product matching and aliases, AI order review, order memory,
staff corrections, payment reminders and the published plans."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest_asyncio
from sqlalchemy import func, select

from app.ai import tools
from app.core.branches import default_branch
from app.core.security import create_access_token, hash_password
from app.db.models.accounts import AccountSettings, SalesInvoice
from app.db.models.collection_reminder import CollectionReminder
from app.db.models.customer import Customer
from app.db.models.escalation import Escalation
from app.db.models.job import Job
from app.db.models.order import Order
from app.db.models.product_alias import ProductAlias
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.session import get_session
from app.jobs.queue import WHATSAPP_COLLECTION_REMINDER
from app.main import app
from app.modules.accounts import service as accounts
from app.modules.billing import service as billing
from app.modules.collections import service as collections
from app.modules.orders import review
from app.modules.orders import service as orders
from app.modules.pricing import service as pricing
from app.modules.products import matching
from app.schemas.order import OrderCreate, OrderItemIn
from app.schemas.pricing import PriceLineIn, PriceListCreate

D = Decimal


@pytest_asyncio.fixture
async def session(db):
    db.sync_session.autoflush = False
    yield db


@pytest_asyncio.fixture
async def client(session):
    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


async def _business(db, stock=500):
    t = Tenant(name="Al Rayyan Fresh", slug=f"t-{uuid.uuid4().hex[:10]}", timezone="Asia/Riyadh")
    db.add(t)
    await db.flush()
    branch = await default_branch(db, t.id)
    branch.whatsapp_phone_number_id, branch.whatsapp_access_token = f"PN-{t.id.hex[:6]}", "tok"
    await db.commit()
    pl = await pricing.create_price_list(db, t.id, PriceListCreate(lines=[
        PriceLineIn(sku="TOM-5", unit_price=D("100"), quantity=stock, currency="SAR", name_en="Tomatoes 5 kg",
                    name_ar="طماطم 5 كيلو"),
        PriceLineIn(sku="MAN-4", unit_price=D("40"), quantity=stock, currency="SAR", name_en="Mangoes 4 kg",
                    name_ar="مانجو 4 كيلو"),
        PriceLineIn(sku="MLK-1L", unit_price=D("6"), quantity=stock, currency="SAR", name_en="Almarai Milk 1L",
                    name_ar="حليب المراعي 1 لتر"),
        PriceLineIn(sku="MLK-2L", unit_price=D("11"), quantity=stock, currency="SAR", name_en="Almarai Milk 2L",
                    name_ar="حليب المراعي 2 لتر"),
    ]), branch_id=branch.id)
    await pricing.activate_price_list(db, t.id, pl.id)
    return t, branch


async def _customer(db, t, branch, phone="+966500000001", name="Al Noor Grocery"):
    c = Customer(tenant_id=t.id, branch_id=branch.id, name=name, whatsapp_number=phone)
    db.add(c)
    await db.commit()
    return c


def _ctx(t, branch, phone="+966500000001"):
    return tools.ToolContext(tenant_id=t.id, branch_id=branch.id, customer_number=phone)


async def _owner(db, t):
    u = User(tenant_id=t.id, email=f"o-{uuid.uuid4().hex[:6]}@x.co", password_hash=hash_password("pw-123456"),
             role="owner")
    db.add(u)
    await db.commit()
    return {"Authorization": f"Bearer {create_access_token(u.id, u.tenant_id, u.role)}"}


# --- normalising and scoring --------------------------------------------------------------

def test_arabic_spelling_variants_normalise_to_the_same_text():
    assert matching.normalise("طماطة") == matching.normalise("طماطه")
    assert matching.normalise("إناء") == matching.normalise("اناء")
    assert matching.normalise("حَلِيب") == matching.normalise("حليب")
    assert matching.normalise("حليب ١ لتر") == "حليب 1 لتر"
    assert matching.normalise("Milk 1 L") == "milk 1l"


def test_scores_reward_the_right_product_and_punish_the_wrong_size():
    name = matching.normalise("Almarai Milk 1L")
    assert matching.similarity(matching.normalise("almarai milk 1l"), name) == 1.0
    assert matching.similarity(matching.normalise("almarai milk"), name) >= 0.9
    assert matching.similarity(matching.normalise("almari milk"), name) >= 0.7  # typo
    assert matching.similarity(matching.normalise("milk 2l"), name) < 0.5  # wrong size
    assert matching.similarity(matching.normalise("the red one"), name) < 0.4


async def test_search_finds_products_from_customer_words(session):
    t, branch = await _business(session)
    found = await tools.dispatch(session, _ctx(t, branch), "search_products", {"query": "almari milk 2 l"})
    assert found["found"] and found["products"][0]["sku"] == "MLK-2L"
    arabic = await tools.dispatch(session, _ctx(t, branch), "search_products", {"query": "طماطم"})
    assert arabic["products"][0]["sku"] == "TOM-5"
    nothing = await tools.dispatch(session, _ctx(t, branch), "search_products", {"query": "zzzz qqqq"})
    assert nothing["found"] is False


async def test_customer_alias_beats_everything_and_stays_with_that_customer(session):
    t, branch = await _business(session)
    c = await _customer(session, t, branch)
    other = await _customer(session, t, branch, phone="+966500000002", name="Other Shop")
    mango = (await matching.find_matches(session, t.id, "mangoes"))[0]["product"]
    await matching.add_alias(session, t.id, mango.id, "the yellow box", customer_id=c.id)

    mine = await matching.find_matches(session, t.id, "The Yellow Box!", customer_id=c.id)
    assert mine[0]["product"].sku == "MAN-4" and mine[0]["score"] == 1.0 and mine[0]["via"] == "customer_alias"
    theirs = await matching.find_matches(session, t.id, "the yellow box", customer_id=other.id)
    assert not theirs or theirs[0]["score"] < 0.6
    alias = await session.scalar(select(ProductAlias))
    assert alias.hits == 2  # 1 on creation + 1 use


# --- AI order review ------------------------------------------------------------------------

async def test_clear_order_is_confirmed_and_the_wording_is_learned(session):
    t, branch = await _business(session)
    c = await _customer(session, t, branch)
    out = await tools.dispatch(session, _ctx(t, branch), "place_order", {"items": [
        {"sku": "TOM-5", "quantity": 3, "customer_wording": "tomatoes"},
    ]})
    assert out["status"] == "confirmed" and out["needs_human_review"] is False
    learned = await session.scalar(select(ProductAlias).where(ProductAlias.customer_id == c.id))
    assert learned.alias == "tomatoes" and learned.source == "learned"


async def test_doubtful_product_is_held_for_the_team(session):
    t, branch = await _business(session)
    await _customer(session, t, branch)
    out = await tools.dispatch(session, _ctx(t, branch), "place_order", {"items": [
        {"sku": "MAN-4", "quantity": 2, "customer_wording": "the red one"},
    ]})
    assert out["needs_human_review"] and out["review_reason"] == "checking_items"
    esc = await session.scalar(select(Escalation))
    assert esc.reason_type == "ai_review"
    assert esc.context["review"][0]["kind"] == "low_confidence"
    assert esc.context["lines"][0]["wording"] == "the red one"
    order = await session.get(Order, esc.order_id)
    assert order.status == "requires_human_review"


async def test_unusual_quantity_is_held(session):
    t, branch = await _business(session)
    c = await _customer(session, t, branch)
    await orders.create_order(session, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=5)],
                                                         customer_id=c.id))
    out = await tools.dispatch(session, _ctx(t, branch), "place_order", {"items": [
        {"sku": "TOM-5", "quantity": 50, "customer_wording": "tomatoes"},
    ]})
    assert out["needs_human_review"] and out["review_reason"] == "checking_items"
    esc = await session.scalar(select(Escalation).where(Escalation.reason_type == "ai_review"))
    assert esc.context["review"][0]["kind"] == "unusual_quantity"
    assert esc.context["review"][0]["previous_max"] == 5


async def test_shadow_mode_holds_every_ai_order(session):
    t, branch = await _business(session)
    await review.update_settings(session, t.id, {"review_all_ai_orders": True})
    out = await tools.dispatch(session, _ctx(t, branch), "place_order", {"items": [
        {"sku": "TOM-5", "quantity": 1, "customer_wording": "tomatoes 5 kg"},
    ]})
    assert out["needs_human_review"]
    esc = await session.scalar(select(Escalation))
    assert esc.context["review"][0]["kind"] == "shadow_mode"


async def test_unknown_sku_is_reported_to_the_ai_not_raised(session):
    t, branch = await _business(session)
    out = await tools.dispatch(session, _ctx(t, branch), "place_order",
                               {"items": [{"sku": "NOPE", "quantity": 1}]})
    assert out["placed"] is False and "NOPE" in out["error"]


async def test_staff_correction_approves_and_teaches_the_ai(session, client):
    t, branch = await _business(session)
    c = await _customer(session, t, branch)
    await tools.dispatch(session, _ctx(t, branch), "place_order", {"items": [
        {"sku": "MAN-4", "quantity": 2, "customer_wording": "the red one"},
    ]})
    esc = await session.scalar(select(Escalation))
    h = await _owner(session, t)
    r = await client.post(f"/api/v1/orders/escalations/{esc.id}/correct", headers=h, json={
        "items": [{"sku": "TOM-5", "quantity": 2, "wording": "the red one"}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["resolution"] == "approved"
    order = await session.get(Order, esc.order_id)
    await session.refresh(order)
    assert order.status in ("confirmed", "preparing")
    assert [i.sku for i in order.items] == ["TOM-5"] and order.total_amount == D("200")

    again = await matching.find_matches(session, t.id, "the red one", customer_id=c.id)
    assert again[0]["product"].sku == "TOM-5" and again[0]["score"] == 1.0
    # next time the same words go straight through
    out = await tools.dispatch(session, _ctx(t, branch), "place_order", {"items": [
        {"sku": "TOM-5", "quantity": 2, "customer_wording": "the red one"},
    ]})
    assert out["status"] == "confirmed"


async def test_correction_cannot_touch_a_resolved_escalation(session, client):
    t, branch = await _business(session)
    await tools.dispatch(session, _ctx(t, branch), "place_order", {"items": [
        {"sku": "MAN-4", "quantity": 2, "customer_wording": "the red one"},
    ]})
    esc = await session.scalar(select(Escalation))
    await orders.resolve_escalation(session, t.id, esc.id, approve=False)
    h = await _owner(session, t)
    r = await client.post(f"/api/v1/orders/escalations/{esc.id}/correct", headers=h,
                          json={"items": [{"sku": "TOM-5", "quantity": 1}]})
    assert r.status_code == 409


# --- order memory ----------------------------------------------------------------------------

async def test_order_history_gives_recent_orders_and_usual_items(session):
    t, branch = await _business(session)
    c = await _customer(session, t, branch)
    for qty in (4, 6, 5):
        await orders.create_order(session, t.id, OrderCreate(
            items=[OrderItemIn(sku="TOM-5", quantity=qty), OrderItemIn(sku="MLK-1L", quantity=10)],
            customer_id=c.id,
        ))
    await orders.create_order(session, t.id, OrderCreate(items=[OrderItemIn(sku="MAN-4", quantity=1)],
                                                         customer_id=c.id))
    out = await tools.dispatch(session, _ctx(t, branch), "get_my_order_history", {})
    assert out["has_history"] and len(out["recent_orders"]) == 3
    assert out["recent_orders"][0]["items"][0]["sku"] == "MAN-4"
    usual = {u["sku"]: u for u in out["usual_items"]}
    assert usual["TOM-5"]["times_ordered"] == 3 and usual["TOM-5"]["typical_quantity"] == 5
    assert usual["MLK-1L"]["typical_quantity"] == 10

    stranger = await tools.dispatch(session, _ctx(t, branch, phone="+966599999999"), "get_my_order_history", {})
    assert stranger["has_history"] is False


# --- payment reminders --------------------------------------------------------------------------

def test_reminder_stages():
    s = AccountSettings(reminder_days_before_due=3, reminder_repeat_days=7, reminder_max_overdue=3)
    due = date(2026, 12, 10)
    assert collections.stage_for(due, date(2026, 12, 6), s) is None
    assert collections.stage_for(due, date(2026, 12, 7), s) == "due_soon"
    assert collections.stage_for(due, date(2026, 12, 10), s) is None  # due today: no nagging
    assert collections.stage_for(due, date(2026, 12, 11), s) == "overdue_1"
    assert collections.stage_for(due, date(2026, 12, 17), s) == "overdue_1"
    assert collections.stage_for(due, date(2026, 12, 18), s) == "overdue_2"
    assert collections.stage_for(due, date(2026, 12, 25), s) == "overdue_3"
    assert collections.stage_for(due, date(2027, 1, 1), s) is None  # max reached


async def _overdue_invoice(session, t, c, days_overdue=2):
    order = await orders.create_order(session, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=1)],
                                                                 customer_id=c.id))
    for st in ("dispatched", "delivered"):
        order = await orders.transition_order(session, t.id, order.id, st)
    inv = await session.scalar(select(SalesInvoice).where(SalesInvoice.order_id == order.id))
    inv.due_date = accounts.tenant_today(t) - timedelta(days=days_overdue)
    await session.commit()
    return inv


async def test_reminders_are_queued_once_per_stage(session):
    t, branch = await _business(session)
    c = await _customer(session, t, branch)
    inv = await _overdue_invoice(session, t, c)
    assert await collections.queue_due_reminders(session, t.id, ignore_hours=True) == 0  # switched off
    await accounts.update_settings(session, t.id, {"reminders_enabled": True})
    assert await collections.queue_due_reminders(session, t.id, ignore_hours=True) == 1
    assert await collections.queue_due_reminders(session, t.id, ignore_hours=True) == 0
    r = await session.scalar(select(CollectionReminder))
    assert r.invoice_id == inv.id and r.stage == "overdue_1" and r.status == "queued"
    assert await session.scalar(select(func.count(Job.id)).where(Job.kind == WHATSAPP_COLLECTION_REMINDER)) == 1


async def test_reminders_wait_for_business_hours(session):
    t, branch = await _business(session)
    c = await _customer(session, t, branch)
    await _overdue_invoice(session, t, c)
    await accounts.update_settings(session, t.id, {"reminders_enabled": True})
    night = datetime(2026, 11, 21, 23, 30, tzinfo=timezone.utc)  # 02:30 in Riyadh
    assert await collections.queue_due_reminders(session, t.id, now=night) == 0


async def test_reminder_uses_the_template_outside_the_window(session, monkeypatch):
    from app.channels.whatsapp import service as whatsapp
    sent = []

    async def fake_template(branch, to, name, language, params):
        sent.append((to, name, language, params))
        return {}

    monkeypatch.setattr(whatsapp, "send_template", fake_template)
    t, branch = await _business(session)
    c = await _customer(session, t, branch)
    inv = await _overdue_invoice(session, t, c)
    await accounts.update_settings(session, t.id, {"reminders_enabled": True})
    await collections.queue_due_reminders(session, t.id, ignore_hours=True)
    r = await session.scalar(select(CollectionReminder))

    assert await collections.send_reminder(session, r.id) == "skipped:outside the 24-hour window and no reminder template set"
    r.status = "queued"
    await session.commit()
    await accounts.update_settings(session, t.id, {"reminder_template": "payment_reminder"})
    assert await collections.send_reminder(session, r.id) == "sent_template"
    to, name, language, params = sent[0]
    assert to == "966500000001" and name == "payment_reminder" and params[1] == inv.number
    # a reminder goes out once
    assert await collections.send_reminder(session, r.id) == "skipped:already handled"


async def test_reminders_api(session, client):
    t, branch = await _business(session)
    c = await _customer(session, t, branch)
    await _overdue_invoice(session, t, c)
    h = await _owner(session, t)
    r = await client.put("/api/v1/accounts/settings", headers=h, json={"reminders_enabled": True,
                                                                     "reminder_repeat_days": 5})
    assert r.status_code == 200 and r.json()["reminders_enabled"] is True and r.json()["reminder_repeat_days"] == 5
    await collections.queue_due_reminders(session, t.id, ignore_hours=True)
    listed = (await client.get("/api/v1/accounts/reminders", headers=h)).json()
    assert listed[0]["stage"] == "overdue_1" and listed[0]["customer_name"] == "Al Noor Grocery"


# --- aliases and settings over the API ---------------------------------------------------------------

async def test_alias_and_agent_settings_api(session, client):
    t, branch = await _business(session)
    h = await _owner(session, t)
    match = (await client.get("/api/v1/products/match", headers=h, params={"q": "mangos"})).json()
    assert match[0]["sku"] == "MAN-4"
    product_id = match[0]["product_id"]

    r = await client.post(f"/api/v1/products/{product_id}/aliases", headers=h, json={"alias": "أبو صندوق أصفر"})
    assert r.status_code == 201 and r.json()["source"] == "manual"
    assert (await client.post(f"/api/v1/products/{product_id}/aliases", headers=h,
                              json={"alias": "Mangoes 4 kg"})).status_code == 422
    listed = (await client.get("/api/v1/products/aliases", headers=h)).json()
    assert len(listed) == 1 and listed[0]["sku"] == "MAN-4"
    found = (await client.get("/api/v1/products/match", headers=h, params={"q": "ابو صندوق اصفر"})).json()
    assert found[0]["sku"] == "MAN-4" and found[0]["matched_by"] == "alias"
    assert (await client.delete(f"/api/v1/products/aliases/{listed[0]['id']}", headers=h)).status_code == 204

    s = (await client.get("/api/v1/agent/settings", headers=h)).json()
    assert s["review_min_confidence"] == 0.6 and s["review_all_ai_orders"] is False
    s = (await client.put("/api/v1/agent/settings", headers=h, json={"review_all_ai_orders": True})).json()
    assert s["review_all_ai_orders"] is True


# --- plans --------------------------------------------------------------------------------------

async def test_new_subscription_starts_on_the_pilot_plan(session):
    t, _ = await _business(session)
    sub = await billing.upsert_subscription(session, t.id, {"next_invoice_on": date(2026, 12, 1)})
    assert sub.plan == "pilot" and sub.currency == "SAR" and sub.monthly_fee_per_branch == D("2500")
    sub = await billing.upsert_subscription(session, t.id, {"plan": "growth"})
    assert sub.setup_fee_per_branch == D("7500") and sub.included_orders_per_branch == 5000
    sub = await billing.upsert_subscription(session, t.id, {"monthly_fee_per_branch": D("3200")})
    assert sub.plan == "custom" and sub.monthly_fee_per_branch == D("3200")
    sub = await billing.upsert_subscription(session, t.id, {"plan": "custom", "included_orders_per_branch": None,
                                                            "overage_per_order": None})
    assert sub.included_orders_per_branch is None and sub.overage_per_order is None


async def test_orders_above_the_plan_are_billed_next_month(session):
    t, _ = await _business(session, stock=5000)
    sub = await billing.upsert_subscription(session, t.id, {"next_invoice_on": date(2026, 12, 1),
                                                            "included_orders_per_branch": 2})
    sub.created_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for _ in range(5):
        o = await orders.create_order(session, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=1)]))
        o.confirmed_at = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
    await session.commit()
    inv = await billing.issue_next_monthly(session, t.id, on=date(2026, 12, 1))
    assert len(inv.lines) == 2
    assert inv.lines[1]["quantity"] == "3" and inv.lines[1]["unit_amount"] == "0.60"
    assert inv.subtotal == D("2501.80")
