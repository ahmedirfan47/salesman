"""ERP integration (Odoo) against an in-memory Odoo: connecting, prices and stock, order-to-cash, retries."""
import uuid
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.config import settings as app_settings
from app.core.branches import default_branch
from app.core.security import create_access_token, hash_password
from app.db.models.branch import Branch
from app.db.models.customer import Customer
from app.db.models.integration import IntegrationEvent, IntegrationLink
from app.db.models.inventory_transaction import InventoryTransaction
from app.db.models.job import Job
from app.db.models.price_list import PriceList
from app.db.models.product import Product
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.session import get_session
from app.jobs.queue import ERP_PULL, ERP_PUSH
from app.main import app
from app.modules.accounts import service as accounts
from app.modules.integrations import odoo_client, service
from app.modules.integrations.odoo_client import OdooAuthError, OdooUnavailable, check_url
from app.modules.orders import service as orders
from app.modules.pricing import service as pricing
from app.schemas.order import OrderCreate, OrderItemIn
from tests.fake_odoo import KEY, FakeOdoo

D = Decimal
URL = "https://acme.odoo.com"


@pytest_asyncio.fixture
async def session(db):
    db.sync_session.autoflush = False
    yield db


@pytest.fixture
def fake():
    f = FakeOdoo()
    odoo_client.TRANSPORT = httpx.MockTransport(f.handler)
    yield f
    odoo_client.TRANSPORT = None


@pytest_asyncio.fixture
async def client(session):
    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


async def _business(db):
    t = Tenant(name="Al Rayyan Fresh", slug=f"t-{uuid.uuid4().hex[:10]}", timezone="Asia/Riyadh")
    db.add(t)
    await db.flush()
    main = await default_branch(db, t.id)
    jeddah = Branch(tenant_id=t.id, name="Jeddah", city="Jeddah", is_default=False, is_active=True)
    db.add(jeddah)
    await db.commit()
    await accounts.update_settings(db, t.id, {"currency": "SAR", "vat_rate": D("15"), "prices_include_vat": False,
                                              "default_payment_terms_days": 30})
    c = Customer(tenant_id=t.id, branch_id=main.id, name="Al Noor Grocery", company="Al Noor Grocery LLC",
                 whatsapp_number="+966500000001", vat_number="310000000000003", cr_number="1010123456",
                 street="Olaya St", building_number="1234", district="Al Olaya", city="Riyadh", postal_code="12241")
    db.add(c)
    await db.commit()
    return t, main, jeddah, c


async def _connect(db, t, *, activate=True, **kw):
    conn, options = await service.connect(db, t.id, provider="odoo", url=kw.get("url", URL), database="acme",
                                          username=kw.get("username", "admin"), api_key=kw.get("api_key", KEY))
    if activate:
        conn = await service.activate(db, conn)
    return conn, options


async def drain(db) -> list[str]:
    out = []
    while True:
        job = await db.scalar(select(Job).where(Job.kind.in_((ERP_PUSH, ERP_PULL)), Job.status == "queued")
                              .order_by(Job.run_after, Job.created_at).limit(1))
        if job is None:
            return out
        job.status = "done"
        await db.commit()
        run = service.run_push if job.kind == ERP_PUSH else service.run_pull
        out.append(f"{job.payload.get('action', 'pull')}={await run(db, job.payload)}")


async def _event(db, action, label) -> IntegrationEvent:
    return await db.scalar(select(IntegrationEvent).where(IntegrationEvent.action == action, IntegrationEvent.label == label))


async def _stock(db, t, branch, sku):
    return (await pricing.get_current_price(db, t.id, sku, branch.id))


# --- connecting ------------------------------------------------------------------------------

async def test_connect_proposes_a_complete_mapping(session, fake):
    db = session
    t, main, jeddah, _ = await _business(db)
    conn, options = await _connect(db, t, activate=False)
    s = conn.settings
    assert conn.api == "json2" and conn.server_version == "19.0" and conn.status == "draft"
    assert s["company_id"] == fake.company and s["sales_journal_id"] == fake.sales_journal
    assert s["taxes"] == {"15.00": fake.tax15, "0.00": fake.tax0}
    assert s["payment_journals"]["cash"] == fake.cash and s["payment_journals"]["bank_transfer"] == fake.bank
    assert s["branches"][str(main.id)]["warehouse_id"] == fake.wh_ruh
    assert s["branches"][str(jeddah.id)]["warehouse_id"] == fake.wh_jed   # matched by name
    assert s["fields"]["sale_line_tax"] == "tax_ids" and s["fields"]["arabic_lang"] == "ar_001"
    assert await service.problems(db, conn, options) == []
    assert KEY not in conn.secret   # sealed

    with pytest.raises(HTTPException, match="refused the API key"):
        await service.connect(db, t.id, provider="odoo", url=URL, database="acme", username="admin", api_key="wrong")
    with pytest.raises(HTTPException, match="not available yet"):
        await service.connect(db, t.id, provider="qoyod", url=URL, database=None, username=None, api_key="k")


async def test_older_odoo_uses_json_rpc_and_needs_the_login(session, fake):
    db = session
    fake.version = 18
    t, *_ = await _business(db)
    with pytest.raises(HTTPException, match="needs the login"):
        await service.connect(db, t.id, provider="odoo", url=URL, database="acme", username=None, api_key=KEY)
    conn, _ = await _connect(db, t, activate=False)
    assert conn.api == "jsonrpc" and conn.server_version == "18.0"


async def test_switching_on_needs_a_complete_mapping(session, fake):
    db = session
    t, main, *_ = await _business(db)
    conn, _ = await _connect(db, t, activate=False)
    await service.update_settings(db, conn, {"taxes": {"15.00": None}, "branches": {str(main.id): {"warehouse_id": None}}})
    with pytest.raises(HTTPException) as exc:
        await service.activate(db, conn)
    assert "VAT 15.00%" in exc.value.detail and "warehouse for: Main branch." in exc.value.detail


def test_only_public_https_addresses_are_accepted(monkeypatch):
    monkeypatch.setattr(app_settings, "ERP_ALLOW_PRIVATE_URLS", False)
    for url in ("http://acme.odoo.com", "https://127.0.0.1:8069", "https://10.1.2.3", "https://169.254.169.254",
                "https://[::1]", "ftp://acme.odoo.com"):
        with pytest.raises(OdooAuthError):
            check_url(url)
    assert check_url("acme.odoo.com/odoo/") == "https://acme.odoo.com"
    monkeypatch.setattr(app_settings, "ERP_ALLOW_PRIVATE_URLS", True)
    assert check_url("http://127.0.0.1:8069") == "http://127.0.0.1:8069"


async def test_redirects_are_not_followed(session, fake):
    db = session
    t, *_ = await _business(db)
    fake.redirect_to = "http://169.254.169.254/latest/meta-data"
    with pytest.raises(HTTPException, match="sent us to another address"):
        await _connect(db, t, activate=False)


# --- prices and stock ------------------------------------------------------------------------

async def test_prices_and_stock_come_from_odoo_per_branch(session, fake):
    db = session
    t, main, jeddah, _ = await _business(db)
    conn, _ = await _connect(db, t, activate=False)
    await service.update_settings(db, conn, {"branches": {str(jeddah.id): {"warehouse_id": fake.wh_jed,
                                                                          "pricelist_id": fake.pricelist}}})
    await service.activate(db, conn)
    assert await drain(db) == ["pull=warning"]

    tom = await _stock(db, t, main, "TOM-5")
    assert (tom["unit_price"], tom["quantity_on_hand"], tom["currency"]) == (D("100.00"), 120, "SAR")
    assert (await _stock(db, t, main, "CUC-10"))["quantity_on_hand"] == 0
    tom_j = await _stock(db, t, jeddah, "TOM-5")
    assert (tom_j["unit_price"], tom_j["quantity_on_hand"]) == (D("95.00"), 40)      # Jeddah price list
    assert (await _stock(db, t, jeddah, "MAN-4"))["unit_price"] == D("40.00")       # no rule: sales price
    product = await db.scalar(select(Product).where(Product.tenant_id == t.id, Product.sku == "TOM-5"))
    assert product.name_ar == "طماطم 5 كجم" and product.cost_price == D("62.50")
    skus = set(await db.scalars(select(Product.sku).where(Product.tenant_id == t.id)))
    assert skus == {"TOM-5", "MAN-4", "CUC-10"}   # no internal reference / not stock-tracked: left out
    ev = await db.scalar(select(IntegrationEvent).where(IntegrationEvent.action == "catalog"))
    assert "percentages, formulas or categories" in ev.message

    # unchanged prices: only stock moves, no new price list version
    lists = await db.scalar(select(func.count(PriceList.id)).where(PriceList.tenant_id == t.id))
    fake.stock[(fake.wh_ruh, fake.products["TOM-5"])] = 80
    await service.sync_now(db, conn)
    assert await drain(db) == ["pull=warning"]
    assert (await _stock(db, t, main, "TOM-5"))["quantity_on_hand"] == 80
    assert await db.scalar(select(func.count(PriceList.id)).where(PriceList.tenant_id == t.id)) == lists
    assert await db.scalar(select(func.count(InventoryTransaction.id)).where(InventoryTransaction.reason == "erp_sync")) == 1

    # a price change in Odoo makes a new version
    fake.db["product.product"][fake.products["MAN-4"]]["lst_price"] = 42.0
    await service.sync_now(db, conn)
    await drain(db)
    assert (await _stock(db, t, main, "MAN-4"))["unit_price"] == D("42.00")


async def test_an_empty_odoo_never_wipes_the_price_list(session, fake):
    db = session
    t, main, *_ = await _business(db)
    conn, _ = await _connect(db, t)
    await drain(db)
    for p in fake.db["product.product"].values():
        p["sale_ok"] = False
    await service.sync_now(db, conn)
    assert await drain(db) == ["pull=failed"]
    assert (await _stock(db, t, main, "TOM-5"))["unit_price"] == D("100.00")
    await db.refresh(conn)
    assert "Nothing was changed" in conn.last_error


# --- order to cash ---------------------------------------------------------------------------

async def test_order_to_cash_in_odoo(session, fake):
    db = session
    t, main, _, c = await _business(db)
    conn, _ = await _connect(db, t)
    await drain(db)
    tom = fake.products["TOM-5"]

    order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=3)], customer_id=c.id))
    assert (await _stock(db, t, main, "TOM-5"))["quantity_on_hand"] == 117
    # a fetch that runs before the order reaches Odoo keeps the promised units aside
    assert await service.run_pull(db, {"connection_id": str(conn.id)}) == "ok"
    assert (await _stock(db, t, main, "TOM-5"))["quantity_on_hand"] == 117
    assert await drain(db) == ["order.confirmed=ok"]

    so = next(iter(fake.db["sale.order"].values()))
    assert so["state"] == "sale" and so["client_order_ref"] == order.order_number and so["warehouse_id"] == fake.wh_ruh
    assert fake.reserved[(fake.wh_ruh, tom)] == 3
    partner = fake.db["res.partner"][so["partner_id"]]
    assert partner["vat"] == "310000000000003" and partner["company_registry"] == "1010123456"
    assert partner["street"] == "1234 Olaya St" and partner["country_id"] == fake.country_sa
    # Odoo now reserves the units itself: the next fetch agrees
    await service.sync_now(db, conn)
    await drain(db)
    assert (await _stock(db, t, main, "TOM-5"))["quantity_on_hand"] == 117

    await orders.transition_order(db, t.id, order.id, "dispatched")
    await orders.transition_order(db, t.id, order.id, "delivered")
    inv = await accounts.invoice_for_order(db, order.id)
    assert await drain(db) == ["invoice=ok", "order.delivered=ok"]
    picking = fake.db["stock.picking"][so["picking_ids"][0]]
    assert picking["state"] == "done" and fake.stock[(fake.wh_ruh, tom)] == 117
    move = next(m for m in fake.db["account.move"].values() if m.get("ref") == inv.number)
    assert move["state"] == "posted" and move["amount_total"] == 345.0 and move["invoice_origin"] == so["name"]
    assert move["journal_id"] == fake.sales_journal and move["invoice_date_due"] == inv.due_date.isoformat()
    assert fake.db["sale.order.line"][so["order_line"][0]]["qty_invoiced"] == 3

    pay = await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=None, amount=D("100"), method="cash",
                                        reference=None, paid_on=None, notes=None, actor_id=None)
    assert await drain(db) == ["payment=ok"]
    odoo_pay = next(p for p in fake.db["account.payment"].values() if p["memo"] == pay.number)
    assert odoo_pay["journal_id"] == fake.cash and odoo_pay["state"] == "in_process"
    assert move["amount_residual"] == 245.0

    note = await accounts.issue_credit_note(db, t.id, inv.id, amount=D("46"), reason="2 boxes damaged")
    assert await drain(db) == ["invoice=ok"]
    refund = next(m for m in fake.db["account.move"].values() if m.get("ref") == note.number)
    assert refund["move_type"] == "out_refund" and refund["reversed_entry_id"] == move["id"] and refund["amount_total"] == 46.0
    assert move["amount_residual"] == 199.0 == float(await _invoice_due(db, inv))

    rows = await service.balances(db, conn)
    assert [(r["salesman"], r["odoo"], r["difference"]) for r in rows] == [(D("199.00"), D("199.00"), D("0.00"))]

    await accounts.void_payment(db, t.id, pay.id, reason="Counterfeit notes")
    assert await drain(db) == ["payment.void=ok"]
    assert odoo_pay["state"] == "canceled" and move["amount_residual"] == 299.0
    assert (await service.balances(db, conn))[0]["difference"] == 0


async def _invoice_due(db, inv):
    await db.refresh(inv)
    return inv.balance_due


async def test_money_on_account_is_matched_when_the_next_invoice_arrives(session, fake):
    db = session
    t, main, _, c = await _business(db)
    conn, _ = await _connect(db, t)
    await drain(db)
    pay = await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=None, amount=D("500"), method="bank_transfer",
                                        reference="TRX 9", paid_on=None, notes=None, actor_id=None)
    order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="MAN-4", quantity=2)], customer_id=c.id))
    await orders.transition_order(db, t.id, order.id, "dispatched")
    await orders.transition_order(db, t.id, order.id, "delivered")
    await drain(db)
    inv = await accounts.invoice_for_order(db, order.id)
    move = next(m for m in fake.db["account.move"].values() if m.get("ref") == inv.number)
    assert inv.status == "paid" and move["amount_residual"] == 0.0
    assert (await service.balances(db, conn))[0]["difference"] == 0
    assert pay.number in {p["memo"] for p in fake.db["account.payment"].values()}


async def test_cancelled_orders_are_cancelled_in_odoo(session, fake):
    db = session
    t, main, _, c = await _business(db)
    await _connect(db, t)
    await drain(db)
    order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=5)], customer_id=c.id))
    await drain(db)
    await orders.transition_order(db, t.id, order.id, "cancelled")
    assert await drain(db) == ["order.cancelled=ok"]
    so = next(iter(fake.db["sale.order"].values()))
    assert so["state"] == "cancel" and fake.reserved[(fake.wh_ruh, fake.products["TOM-5"])] == 0


async def test_an_invoice_still_goes_when_its_order_cannot(session, fake):
    db = session
    t, main, _, c = await _business(db)
    conn, _ = await _connect(db, t)
    await drain(db)
    # the product's Internal Reference was changed in Odoo after the last fetch
    fake.db["product.product"][fake.products["TOM-5"]]["default_code"] = "TOM-5-OLD"
    for link in await db.scalars(select(IntegrationLink).where(IntegrationLink.entity == "product")):
        await db.delete(link)
    await db.commit()
    order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=1)], customer_id=c.id))
    await orders.transition_order(db, t.id, order.id, "dispatched")
    await orders.transition_order(db, t.id, order.id, "delivered")
    assert await drain(db) == ["order.confirmed=failed", "invoice=ok", "order.delivered=failed"]
    ev = await _event(db, "order.confirmed", order.order_number)
    assert "no matching Internal Reference in Odoo: TOM-5" in ev.message
    inv = await accounts.invoice_for_order(db, order.id)
    move = next(m for m in fake.db["account.move"].values() if m.get("ref") == inv.number)
    assert move["state"] == "posted" and "invoice_origin" not in move and move["amount_total"] == 115.0
    assert (await service.balances(db, conn))[0]["difference"] == 0


# --- reliability ------------------------------------------------------------------------------

async def test_resending_never_duplicates(session, fake):
    db = session
    t, main, _, c = await _business(db)
    conn, _ = await _connect(db, t)
    await drain(db)
    order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=1)], customer_id=c.id))
    await orders.transition_order(db, t.id, order.id, "dispatched")
    await orders.transition_order(db, t.id, order.id, "delivered")
    await drain(db)
    inv = await accounts.invoice_for_order(db, order.id)
    moves = len(fake.db["account.move"])
    # as if the reply was lost after Odoo created everything
    for link in await db.scalars(select(IntegrationLink).where(IntegrationLink.entity.in_(("invoice", "order", "customer")))):
        await db.delete(link)
    await db.commit()
    event = await _event(db, "invoice", inv.number)
    await service.retry(db, conn, event.id)
    assert await drain(db) == ["invoice=ok"]
    assert len(fake.db["account.move"]) == moves and len(fake.db["sale.order"]) == 1 and len(fake.db["res.partner"]) == 1


async def test_odoo_being_down_is_retried_then_goes_through(session, fake):
    db = session
    t, main, _, c = await _business(db)
    await _connect(db, t)
    await drain(db)
    fake.down = True
    order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=1)], customer_id=c.id))
    job = await db.scalar(select(Job).where(Job.kind == ERP_PUSH, Job.status == "queued"))
    with pytest.raises(OdooUnavailable):
        await service.run_push(db, job.payload)
    event = await _event(db, "order.confirmed", order.order_number)
    assert event.status == "failed" and "Retrying automatically" in event.message
    fake.down = False
    assert await service.run_push(db, job.payload) == "ok"
    await db.refresh(event)
    assert event.status == "ok" and event.attempts == 2


async def test_a_mapping_problem_is_reported_and_not_retried(session, fake):
    db = session
    t, main, _, c = await _business(db)
    conn, _ = await _connect(db, t)
    await drain(db)
    conn.settings = {**conn.settings, "payment_journals": {k: v for k, v in conn.settings["payment_journals"].items() if k != "cash"}}
    await db.commit()
    pay = await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=None, amount=D("10"), method="cash",
                                        reference=None, paid_on=None, notes=None, actor_id=None)
    assert await drain(db) == ["payment=failed"]
    event = await _event(db, "payment", pay.number)
    assert event.status == "failed" and "No Odoo journal is chosen for cash payments" in event.message
    events = await service.list_events(db, conn, status_="attention")
    assert [e.label for e in events] == [pay.number]


async def test_nothing_is_sent_until_switched_on_or_while_paused(session, fake):
    db = session
    t, main, _, c = await _business(db)
    conn, _ = await _connect(db, t, activate=False)
    await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=None, amount=D("10"), method="cash",
                                  reference=None, paid_on=None, notes=None, actor_id=None)
    assert await db.scalar(select(func.count(Job.id)).where(Job.kind == ERP_PUSH)) == 0
    await service.activate(db, conn)
    await drain(db)
    await service.pause(db, conn)
    await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=None, amount=D("20"), method="cash",
                                  reference=None, paid_on=None, notes=None, actor_id=None)
    assert await db.scalar(select(func.count(Job.id)).where(Job.kind == ERP_PUSH)) == 0
    assert fake.db["account.payment"] == {}


async def test_json_rpc_order_to_invoice(session, fake):
    db = session
    fake.version = 18
    t, main, _, c = await _business(db)
    conn, _ = await _connect(db, t)
    assert conn.api == "jsonrpc"
    await drain(db)
    order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=2)], customer_id=c.id))
    await orders.transition_order(db, t.id, order.id, "dispatched")
    await orders.transition_order(db, t.id, order.id, "delivered")
    assert await drain(db) == ["order.confirmed=ok", "invoice=ok", "order.delivered=ok"]
    assert (await service.balances(db, conn))[0]["difference"] == 0


async def test_customer_changes_follow_to_odoo(session, fake):
    db = session
    t, main, _, c = await _business(db)
    await _connect(db, t)
    await drain(db)
    await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=1)], customer_id=c.id))
    await drain(db)
    from app.modules.customers import service as customers
    await customers.update_customer(db, t.id, c.id, address="New address", company="Al Noor Trading LLC")
    assert await drain(db) == ["customer=ok"]
    assert fake.db["res.partner"][1]["name"] == "Al Noor Trading LLC"


# --- API -------------------------------------------------------------------------------------

async def _user(db, t, role):
    u = User(tenant_id=t.id, email=f"{role}-{uuid.uuid4().hex[:6]}@x.co", role=role, password_hash=hash_password("pw-123456"))
    db.add(u)
    await db.commit()
    return {"Authorization": f"Bearer {create_access_token(u.id, u.tenant_id, u.role)}"}


async def test_api(session, client, fake):
    db = session
    t, main, jeddah, c = await _business(db)
    owner, rep = await _user(db, t, "owner"), await _user(db, t, "salesman")
    assert (await client.get("/api/v1/integrations", headers=rep)).status_code == 403

    r = await client.get("/api/v1/integrations", headers=owner)
    assert r.status_code == 200 and r.json()["connection"] is None
    assert [p["key"] for p in r.json()["providers"]] == ["odoo", "zoho_books", "qoyod", "sap_b1"]

    body = {"provider": "odoo", "url": "acme.odoo.com/odoo", "database": "acme", "username": "admin", "api_key": "bad"}
    r = await client.post("/api/v1/integrations/connect", json=body, headers=owner)
    assert r.status_code == 422 and "API key" in r.json()["detail"]
    r = await client.post("/api/v1/integrations/connect", json={**body, "api_key": KEY}, headers=owner)
    assert r.status_code == 200 and r.json()["problems"] == []
    assert r.json()["connection"]["base_url"] == "https://acme.odoo.com" and len(r.json()["options"]["warehouses"]) == 2

    r = await client.put("/api/v1/integrations/settings", headers=owner, json={
        "branches": {str(jeddah.id): {"warehouse_id": fake.wh_jed, "pricelist_id": fake.pricelist}, str(uuid.uuid4()): {"warehouse_id": 1}},
        "pull_interval_minutes": 30,
    })
    assert r.status_code == 200 and r.json()["settings"]["pull_interval_minutes"] == 30
    assert set(r.json()["settings"]["branches"]) == {str(main.id), str(jeddah.id)}

    r = await client.post("/api/v1/integrations/activate", headers=owner)
    assert r.status_code == 200 and r.json()["status"] == "active"
    await drain(db)
    assert (await client.post("/api/v1/integrations/sync", headers=owner)).status_code == 202
    await drain(db)
    events = (await client.get("/api/v1/integrations/events", headers=owner)).json()
    assert len(events) == 2 and events[0]["label"] == "Prices and stock"
    r = await client.post(f"/api/v1/integrations/events/{events[0]['id']}/retry", headers=owner)
    assert r.status_code == 200

    # resaving the connection without retyping the key keeps it
    r = await client.post("/api/v1/integrations/connect", json={**body, "api_key": ""}, headers=owner)
    assert r.status_code == 200
    assert (await client.get("/api/v1/integrations/balances", headers=owner)).json() == []
    overview = (await client.get("/api/v1/integrations", headers=owner)).json()
    assert overview["connection"]["status"] == "active" and overview["problems"] == []

    assert (await client.post("/api/v1/integrations/pause", headers=owner)).json()["status"] == "paused"
    assert (await client.delete("/api/v1/integrations", headers=owner)).status_code == 204
    assert (await client.get("/api/v1/integrations", headers=owner)).json()["connection"] is None