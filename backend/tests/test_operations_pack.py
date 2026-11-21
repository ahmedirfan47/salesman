"""Monthly AI accuracy report, the reorder agent, on-site print agents and the data-protection pack."""
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.ai import tools
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.data_request import DataRequest
from app.db.models.escalation import Escalation
from app.db.models.message import Message
from app.db.models.order import Order
from app.db.models.print_job import PrintJob
from app.db.models.reorder import ReorderNudge
from app.modules.accounts import service as accounts
from app.modules.orders import review
from app.modules.orders import service as orders
from app.modules.privacy import service as privacy
from app.modules.reorder import service as reorder
from app.modules.reports import accuracy
from app.schemas.order import OrderCreate, OrderItemIn
from tests.test_order_intelligence import _business, _customer, _owner, client, session  # noqa: F401

D = Decimal


# ---- accuracy report -------------------------------------------------------------------------

async def test_monthly_accuracy_per_customer(session):
    db = session
    t, branch = await _business(db)
    noor = await _customer(db, t, branch)
    salam = await _customer(db, t, branch, phone="+966500000002", name="Salam Market")
    await review.update_settings(db, t.id, {"review_all_ai_orders": True})     # shadow mode: every AI order is held

    async def ai_order(c, *lines):
        ctx = tools.ToolContext(tenant_id=t.id, branch_id=branch.id, customer_number=c.whatsapp_number)
        out = await tools._place_order(db, ctx, [{"sku": s, "quantity": q, "customer_wording": s} for s, q in lines])
        order = await db.scalar(select(Order).where(Order.order_number == out["order_number"]))
        esc = await db.scalar(select(Escalation).where(Escalation.order_id == order.id))
        return order, esc

    _, e1 = await ai_order(noor, ("TOM-5", 2), ("MAN-4", 1))
    await orders.resolve_escalation(db, t.id, e1.id, approve=True)                       # approved as is
    _, e2 = await ai_order(noor, ("TOM-5", 2), ("MAN-4", 1))
    await review.correct_held_order(db, t.id, e2.id, [{"sku": "TOM-5", "quantity": 2}, {"sku": "MAN-4", "quantity": 3}])
    _, e3 = await ai_order(salam, ("MLK-1L", 5))
    await orders.resolve_escalation(db, t.id, e3.id, approve=False)                      # rejected
    await ai_order(salam, ("MLK-2L", 1))                                                 # still waiting
    await review.update_settings(db, t.id, {"review_all_ai_orders": False})
    await ai_order(noor, ("TOM-5", 1))                                                   # straight through
    await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=1)], customer_id=noor.id))

    report = await accuracy.monthly(db, t.id, accounts.tenant_today(t).replace(day=1))
    rows = {r["customer"]: r for r in report["customers"]}
    n = rows["Al Noor Grocery"]
    assert (n["orders"], n["confirmed"], n["approved"], n["corrected"]) == (3, 1, 1, 1)     # the manual order isn't counted
    assert n["order_accuracy"] == 66.7 and n["lines"] == 5 and n["lines_changed"] == 1 and n["line_accuracy"] == 80.0
    s = rows["Salam Market"]
    assert (s["orders"], s["rejected"], s["waiting"], s["order_accuracy"], s["line_accuracy"]) == (2, 1, 1, 0.0, 0.0)
    assert report["totals"]["orders"] == 5 and report["totals"]["minutes_saved"] == 2 * accuracy.MINUTES_PER_ORDER
    assert "Al Noor Grocery,3,1,1,1,0,0,66.7" in accuracy.to_csv(report)

    last_month = (accounts.tenant_today(t).replace(day=1) - timedelta(days=1)).replace(day=1)
    assert (await accuracy.monthly(db, t.id, last_month))["totals"]["orders"] == 0


async def test_accuracy_api(session, client):
    t, branch = await _business(session)
    h = await _owner(session, t)
    r = await client.get("/api/v1/reports/accuracy", headers=h)
    assert r.status_code == 200 and r.json()["totals"]["orders"] == 0
    r = await client.get("/api/v1/reports/accuracy.csv?month=2026-10", headers=h)
    assert r.status_code == 200 and r.text.startswith("Month,Customer") and "2026-10" in r.headers["content-disposition"]
    assert (await client.get("/api/v1/reports/accuracy?month=oct", headers=h)).status_code == 422


# ---- reorder agent ---------------------------------------------------------------------------

async def _history(db, t, c, days_ago: list[int], sku="TOM-5", qty=4):
    for d in sorted(days_ago, reverse=True):
        order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku=sku, quantity=qty)], customer_id=c.id))
        order.created_at = datetime.now(timezone.utc) - timedelta(days=d)
        await db.commit()
    return order


def test_typical_gap():
    from datetime import date
    d = date(2026, 11, 1)
    assert reorder.typical_gap([d, d + timedelta(days=7), d + timedelta(days=14), d + timedelta(days=22)]) == 7
    assert reorder.typical_gap([d, d]) is None


async def test_late_customers_get_one_message(session, monkeypatch):
    from app.channels.whatsapp import service as whatsapp
    sent = []

    async def fake_template(branch, to, name, language, params):
        sent.append((to, name, params))
        return {}

    monkeypatch.setattr(whatsapp, "send_template", fake_template)
    db = session
    t, branch = await _business(db)
    late = await _customer(db, t, branch)
    on_time = await _customer(db, t, branch, phone="+966500000002", name="Salam Market")
    new = await _customer(db, t, branch, phone="+966500000003", name="New Shop")
    await _history(db, t, late, [30, 23, 16, 9])         # every 7 days, last 9 days ago: due after 9 (7 x 1.25)
    await _history(db, t, on_time, [21, 14, 7, 2])
    await _history(db, t, new, [10, 3])                   # only 2 orders: not enough rhythm yet

    assert await reorder.queue_due(db, t.id, ignore_hours=True) == 0          # switched off
    await review.update_settings(db, t.id, {"reorder_enabled": True})
    assert await reorder.queue_due(db, t.id, ignore_hours=True) == 1
    assert await reorder.queue_due(db, t.id, ignore_hours=True) == 0          # once per last order
    n = await db.scalar(select(ReorderNudge))
    assert n.customer_id == late.id and n.typical_days == 7 and n.suggested[0]["sku"] == "TOM-5"

    assert await reorder.send_nudge(db, n.id) == "skipped:outside the 24-hour window and no reorder template set"
    n.status = "queued"
    await db.commit()
    await review.update_settings(db, t.id, {"reorder_template": "usual_order"})
    assert await reorder.send_nudge(db, n.id) == "sent_template"
    assert sent == [("966500000001", "usual_order", ["Al Noor Grocery", "4 x Tomatoes 5 kg"])]

    # the customer orders again: the message counts as converted
    await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=4)], customer_id=late.id))
    view = await reorder.overview(db, t.id)
    assert view["stats"]["sent"] == 1 and view["stats"]["converted"] == 1 and view["stats"]["converted_value"] == D("400.00")
    assert view["nudges"][0]["converted_order"] is not None


async def test_reorder_skips_customers_who_ordered_meanwhile(session):
    db = session
    t, branch = await _business(db)
    c = await _customer(db, t, branch)
    await _history(db, t, c, [30, 23, 16, 9])
    await review.update_settings(db, t.id, {"reorder_enabled": True})
    await reorder.queue_due(db, t.id, ignore_hours=True)
    await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="MAN-4", quantity=1)], customer_id=c.id))
    n = await db.scalar(select(ReorderNudge))
    assert await reorder.send_nudge(db, n.id) == "skipped:the customer ordered before the message went out"


# ---- print agents ----------------------------------------------------------------------------

async def test_print_agent_claims_prints_and_retries(session, client):
    db = session
    t, branch = await _business(db)
    c = await _customer(db, t, branch)
    h = await _owner(db, t)
    r = await client.post("/api/v1/printing/agents", headers=h, json={"branch_id": str(branch.id), "name": "Dock PC"})
    assert r.status_code == 200
    key = r.json()["key"]
    agent = {"X-Print-Agent-Key": key}
    assert key.startswith("spa_") and r.json()["agent"]["key_prefix"] == key[:12]

    assert (await client.post("/api/v1/printing/agent/claim", headers={"X-Print-Agent-Key": "spa_wrong"})).status_code == 401
    r = await client.post("/api/v1/printing/agent/heartbeat", headers=agent, json={"printer": "EPSON TM-T20", "version": "1.0"})
    assert r.status_code == 200 and r.json()["branch"] == branch.name

    for _ in range(2):
        await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=1)], customer_id=c.id))
    jobs = (await client.post("/api/v1/printing/agent/claim", headers=agent)).json()
    assert len(jobs) == 2 and all(j["status"] == "printing" for j in jobs)
    assert (await client.post("/api/v1/printing/agent/claim", headers=agent)).json() == []   # not handed out twice

    pdf = await client.get(f"/api/v1/printing/agent/jobs/{jobs[0]['id']}/slip.pdf", headers=agent)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    ok = await client.post(f"/api/v1/printing/agent/jobs/{jobs[0]['id']}/report", headers=agent, json={"ok": True})
    assert ok.json()["status"] == "done"
    bad = await client.post(f"/api/v1/printing/agent/jobs/{jobs[1]['id']}/report", headers=agent,
                            json={"ok": False, "error": "Paper out"})
    assert bad.json()["status"] == "queued" and bad.json()["error"] == "Paper out"   # tried again on the next claim

    # a slip claimed but never reported (PC switched off) is handed out again after a few minutes
    again = (await client.post("/api/v1/printing/agent/claim", headers=agent)).json()
    assert [j["id"] for j in again] == [jobs[1]["id"]]
    job = await db.get(PrintJob, again[0]["id"])
    job.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    await db.commit()
    assert [j["id"] for j in (await client.post("/api/v1/printing/agent/claim", headers=agent)).json()] == [jobs[1]["id"]]

    listed = (await client.get("/api/v1/printing/agents", headers=h)).json()
    assert listed[0]["online"] and listed[0]["printer"] == "EPSON TM-T20"
    assert (await client.delete(f"/api/v1/printing/agents/{listed[0]['id']}", headers=h)).status_code == 204
    assert (await client.post("/api/v1/printing/agent/claim", headers=agent)).status_code == 401
    await db.refresh(job)
    assert job.status == "queued"            # a revoked agent's slips go back to the queue


# ---- data protection -------------------------------------------------------------------------

async def test_export_leaves_out_secrets(session, client):
    db = session
    t, branch = await _business(db)
    c = await _customer(db, t, branch)
    await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=1)], customer_id=c.id))
    h = await _owner(db, t)
    r = await client.get("/api/v1/privacy/export", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert {"customers.json", "orders.json", "order_items.json", "users.json", "README.txt"} <= set(z.namelist())
    assert json.loads(z.read("customers.json"))[0]["name"] == "Al Noor Grocery"
    assert "password_hash" not in json.loads(z.read("users.json"))[0]
    assert "whatsapp_access_token" not in json.loads(z.read("branches.json"))[0]
    req = await db.scalar(select(DataRequest))
    assert req.kind == "export" and req.detail["records"]["orders"] == 1


async def test_erasing_a_customer(session, client):
    db = session
    t, branch = await _business(db)
    c = await _customer(db, t, branch)
    order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=1)], customer_id=c.id))
    conv = Conversation(tenant_id=t.id, branch_id=branch.id, customer_number="966500000001", customer_name="Ahmad")
    db.add(conv)
    await db.flush()
    db.add(Message(tenant_id=t.id, conversation_id=conv.id, direction="in", sender="customer", content="2 tomatoes"))
    await db.commit()
    h = await _owner(db, t)

    for st in ("dispatched", "delivered"):
        await orders.transition_order(db, t.id, order.id, st)
    r = await client.post(f"/api/v1/privacy/customers/{c.id}/erase", headers=h, json={"confirm": True})
    assert r.status_code == 409 and "balance" in r.json()["detail"]          # owes money: settle first
    inv = await accounts.invoice_for_order(db, order.id)
    await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=inv.id, amount=inv.total, method="cash",
                                  reference=None, paid_on=None, notes=None, actor_id=None)

    assert (await client.post(f"/api/v1/privacy/customers/{c.id}/erase", headers=h, json={})).status_code == 422
    r = await client.post(f"/api/v1/privacy/customers/{c.id}/erase", headers=h, json={"confirm": True})
    assert r.status_code == 200 and r.json()["messages_deleted"] == 1 and r.json()["invoices_kept"] == 1
    await db.refresh(c)
    await db.refresh(order)
    await db.refresh(conv)
    assert c.name == privacy.ERASED and c.whatsapp_number is None and not c.is_active
    assert order.customer_name == privacy.ERASED and order.whatsapp_number is None
    assert conv.customer_number.startswith("erased-") and conv.customer_name is None
    assert await db.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == conv.id)) == 0
    assert (await client.post(f"/api/v1/privacy/customers/{c.id}/erase", headers=h, json={"confirm": True})).status_code == 409
    log = (await client.get("/api/v1/privacy/requests", headers=h)).json()
    assert log[0]["kind"] == "erase_customer" and log[0]["requested_by"].endswith("@x.co")


async def test_message_retention(session):
    db = session
    t, branch = await _business(db)
    conv = Conversation(tenant_id=t.id, branch_id=branch.id, customer_number="966500000009")
    db.add(conv)
    await db.flush()
    old = Message(tenant_id=t.id, conversation_id=conv.id, direction="in", sender="customer", content="old")
    db.add_all([old, Message(tenant_id=t.id, conversation_id=conv.id, direction="in", sender="customer", content="new")])
    await db.commit()
    old.created_at = datetime.now(timezone.utc) - timedelta(days=400)
    await db.commit()
    assert await privacy.apply_retention(db, t.id) == 0                      # keeps messages by default
    await review.update_settings(db, t.id, {"message_retention_days": 365})
    assert await privacy.apply_retention_all(db) == 1
    assert [m.content for m in await db.scalars(select(Message).where(Message.conversation_id == conv.id))] == ["new"]
    await review.update_settings(db, t.id, {"message_retention_days": 0})
    assert (await review.get_settings(db, t.id)).message_retention_days is None
    assert await db.scalar(select(func.count()).select_from(Customer)) == 0
