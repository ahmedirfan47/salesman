"""SAP Business One and Dynamics 365 Business Central connectors against in-memory fakes,
plus the production checks every connector shares: test connection, dry run, health and pausing on a bad login."""
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.db.models.integration import IntegrationLink
from app.db.models.product import Product
from app.modules.accounts import service as accounts
from app.modules.integrations import bc_client, odoo_client, sap_client, service
from app.modules.orders import service as orders
from app.schemas.order import OrderCreate, OrderItemIn
from tests import fake_bc as fbc
from tests import fake_sap as fsap
from tests.fake_odoo import KEY, FakeOdoo
from tests.test_integrations import _business, _stock, drain

D = Decimal
SAP_URL = "https://sap.alrayyan.sa:50000"


@pytest_asyncio.fixture
async def session(db):
    db.sync_session.autoflush = False
    yield db


@pytest.fixture
def sap():
    f = fsap.FakeSap()
    sap_client.TRANSPORT = httpx.MockTransport(f.handler)
    yield f
    sap_client.TRANSPORT = None


@pytest.fixture
def bc():
    f = fbc.FakeBc()
    bc_client.TRANSPORT = httpx.MockTransport(f.handler)
    yield f
    bc_client.TRANSPORT = None


@pytest.fixture
def odoo():
    f = FakeOdoo()
    odoo_client.TRANSPORT = httpx.MockTransport(f.handler)
    yield f
    odoo_client.TRANSPORT = None


async def _sap(db, t, *, activate=True, password=fsap.PASSWORD):
    conn, options = await service.connect(db, t.id, provider="sap_b1", url=SAP_URL, database=fsap.DB,
                                          username=fsap.USER, api_key=password)
    if activate:
        conn = await service.activate(db, conn)
    return conn, options


async def _bc(db, t, *, activate=True, secret=fbc.SECRET):
    conn, options = await service.connect(db, t.id, provider="dynamics_bc", url=None, database=fbc.ENV,
                                          username=fbc.CLIENT_ID, api_key=secret, tenant=fbc.TENANT)
    if activate:
        conn = await service.activate(db, conn)
    return conn, options


# ---- SAP Business One -------------------------------------------------------------------------

async def test_sap_connect_proposes_a_complete_mapping(session, sap):
    db = session
    t, main, jeddah, _ = await _business(db)
    conn, options = await _sap(db, t, activate=False)
    s = conn.settings
    assert conn.provider == "sap_b1" and conn.server_version == "1000190" and conn.base_url == SAP_URL
    assert s["company_id"] == fsap.DB and s["company_currency"] == "SAR"
    assert s["taxes"] == {"15.00": "S1", "0.00": "X0"}
    assert s["payment_journals"]["cash"] == "_SYS00000000011" and s["sales_journal_id"] == 1
    assert s["branches"][str(main.id)]["warehouse_id"] == "RUH01"     # "Main" matched "Riyadh Main"
    assert s["branches"][str(jeddah.id)]["warehouse_id"] == "JED01"
    assert s["adjustment_account"] == "_SYS00000000401"
    assert [t_["id"] for t_ in options["taxes"]] == ["S1", "X0"]       # input VAT left out
    assert await service.problems(db, conn, options) == []
    assert fsap.PASSWORD not in conn.secret

    with pytest.raises(HTTPException, match="SAP refused the login"):
        await service.connect(db, t.id, provider="sap_b1", url=SAP_URL, database=fsap.DB, username=fsap.USER,
                              api_key="wrong")
    with pytest.raises(HTTPException, match="Disconnect the current system"):
        await service.connect(db, t.id, provider="odoo", url="https://acme.odoo.com", database="acme",
                              username="admin", api_key="k")


async def test_sap_prices_and_stock_per_warehouse_and_price_list(session, sap):
    db = session
    t, main, jeddah, _ = await _business(db)
    conn, _ = await _sap(db, t)
    assert await drain(db) == ["pull=ok"]           # three items over two pages
    assert (await _stock(db, t, main, "TOM-5"))["unit_price"] == D("100.00")
    assert (await _stock(db, t, main, "TOM-5"))["quantity_on_hand"] == 120
    assert (await _stock(db, t, jeddah, "TOM-5"))["quantity_on_hand"] == 40
    tom = await db.scalar(select(Product).where(Product.tenant_id == t.id, Product.sku == "TOM-5"))
    assert tom.name_ar == "طماطم ٥ كجم" and tom.cost_price == D("70.00")

    await service.update_settings(db, conn, {"branches": {str(jeddah.id): {"warehouse_id": "JED01", "pricelist_id": 2}}})
    preview = await service.dry_run(db, conn)
    jed = next(b for b in preview["branches"] if b["branch"] == "Jeddah")
    assert jed["price_changes"] == 2 and jed["new"] == 0 and jed["not_in_erp"] == ["POT-10"]
    # POT-10 has no wholesale price: left out of Jeddah, with a note
    assert any("no price in SAP price list 2" in n for n in preview["notes"])
    assert (await _stock(db, t, jeddah, "TOM-5"))["unit_price"] == D("100.00")   # the dry run wrote nothing

    await service.sync_now(db, conn)
    assert await drain(db) == ["pull=warning"]
    assert (await _stock(db, t, jeddah, "TOM-5"))["unit_price"] == D("92.00")


async def test_sap_order_to_cash(session, sap):
    db = session
    t, main, _, c = await _business(db)
    conn, _ = await _sap(db, t)
    await drain(db)

    order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=3)], customer_id=c.id))
    assert await drain(db) == ["order.confirmed=ok"]
    so = next(iter(sap.docs["Orders"].values()))
    assert so["NumAtCard"] == order.order_number and so["DocumentLines"][0]["WarehouseCode"] == "RUH01"
    assert so["DocumentLines"][0]["VatGroup"] == "S1" and sap.stock("TOM-5", "RUH01") == (120, 3)
    bp = sap.partners[so["CardCode"]]
    assert bp["FederalTaxID"] == "310000000000003" and bp["AdditionalID"] == "1010123456"
    assert bp["BPAddresses"][0]["Street"] == "1234 Olaya St"
    # SAP now commits the units: the next fetch agrees with Salesman
    await service.sync_now(db, conn)
    await drain(db)
    assert (await _stock(db, t, main, "TOM-5"))["quantity_on_hand"] == 117

    await orders.transition_order(db, t.id, order.id, "dispatched")
    await orders.transition_order(db, t.id, order.id, "delivered")
    inv = await accounts.invoice_for_order(db, order.id)
    assert await drain(db) == ["invoice=ok", "order.delivered=skipped"]   # the invoice copied the order: it delivers too
    sap_inv = next(iter(sap.docs["Invoices"].values()))
    assert sap_inv["NumAtCard"] == inv.number and sap_inv["DocTotal"] == 345.0
    assert sap_inv["DocumentLines"][0]["BaseType"] == 17 and sap.stock("TOM-5", "RUH01") == (117, 0)

    pay = await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=None, amount=D("100"), method="cash",
                                        reference=None, paid_on=None, notes=None, actor_id=None)
    assert await drain(db) == ["payment=ok"]
    sap_pay = next(iter(sap.docs["IncomingPayments"].values()))
    assert sap_pay["Remarks"] == pay.number and sap_pay["CashAccount"] == "_SYS00000000011"
    assert sap_pay["PaymentInvoices"] == [{"DocEntry": sap_inv["DocEntry"], "SumApplied": 100.0, "InvoiceType": "it_Invoice"}]

    note = await accounts.issue_credit_note(db, t.id, inv.id, amount=D("46"), reason="2 boxes damaged")
    assert await drain(db) == ["invoice=ok"]
    memo = next(iter(sap.docs["CreditNotes"].values()))
    assert memo["NumAtCard"] == note.number and memo["DocType"] == "dDocument_Service" and memo["DocTotal"] == 46.0

    rows = await service.balances(db, conn)
    assert [(r["salesman"], r["erp"], r["difference"]) for r in rows] == [(D("199.00"), D("199.00"), D("0.00"))]

    await accounts.void_payment(db, t.id, pay.id, reason="Counterfeit notes")
    assert await drain(db) == ["payment.void=ok"]
    assert sap_pay["Cancelled"] == "tYES" and (await service.balances(db, conn))[0]["difference"] == 0


async def test_sap_retries_are_safe_and_sessions_renew(session, sap):
    db = session
    t, _, _, c = await _business(db)
    conn, _ = await _sap(db, t)
    await drain(db)
    order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="ONI-10", quantity=2)], customer_id=c.id))
    sap.expire_next = True                      # the session timed out: log in again once and carry on
    assert await drain(db) == ["order.confirmed=ok"]
    # the link is lost (say the job died after SAP saved the order): sending again finds the order, no duplicate
    await db.execute(IntegrationLink.__table__.delete().where(IntegrationLink.entity == "order"))
    await db.commit()
    await service.run_push(db, {"connection_id": str(conn.id), "action": "order.confirmed", "id": str(order.id)})
    assert len(sap.docs["Orders"]) == 1

    await orders.transition_order(db, t.id, order.id, "cancelled")
    assert await drain(db) == ["order.cancelled=ok"]
    assert next(iter(sap.docs["Orders"].values()))["Cancelled"] == "tYES" and sap.stock("ONI-10", "RUH01") == (80, 0)


# ---- Dynamics 365 Business Central -----------------------------------------------------------

async def test_bc_connect_and_catalog(session, bc):
    db = session
    t, main, jeddah, _ = await _business(db)
    conn, options = await _bc(db, t, activate=False)
    s = conn.settings
    assert conn.provider == "dynamics_bc" and conn.base_url == bc_client.DEFAULT_API and s["aad_tenant"] == fbc.TENANT
    assert s["company_id"] == bc.company and s["company_currency"] == "SAR"
    assert s["taxes"] == {"15.00": "VAT15", "0.00": "VAT0"} and s["payment_journals"]["cash"] == bc.journal
    assert s["branches"][str(jeddah.id)]["warehouse_id"] != s["branches"][str(main.id)]["warehouse_id"]
    assert await service.problems(db, conn, options) == []

    with pytest.raises(HTTPException, match="Microsoft refused the app's sign-in"):
        await service.connect(db, t.id, provider="dynamics_bc", url=None, database=fbc.ENV, username=fbc.CLIENT_ID,
                              api_key="bad", tenant=fbc.TENANT)

    conn = await service.activate(db, conn)
    assert await drain(db) == ["pull=warning"]      # two branches share the company's stock: noted
    assert (await _stock(db, t, main, "TOM-5"))["unit_price"] == D("100.00")
    assert (await _stock(db, t, jeddah, "ONI-10"))["quantity_on_hand"] == 80


async def test_bc_order_to_cash(session, bc):
    db = session
    t, main, jeddah, c = await _business(db)
    conn, _ = await _bc(db, t)
    await service.update_settings(db, conn, {"branches": {str(jeddah.id): {"warehouse_id": None}}})
    await drain(db)

    order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=3)], customer_id=c.id))
    assert await drain(db) == ["order.confirmed=ok"]
    so = next(iter(bc.orders.values()))
    assert so["externalDocumentNumber"] == order.order_number and len(so["_lines"]) == 1
    assert so["_lines"][0]["taxCode"] == "VAT15" and bc.customers[so["customerId"]]["taxRegistrationNumber"] == "310000000000003"

    await orders.transition_order(db, t.id, order.id, "dispatched")
    await orders.transition_order(db, t.id, order.id, "delivered")
    inv = await accounts.invoice_for_order(db, order.id)
    assert await drain(db) == ["invoice=ok", "order.delivered=skipped"]
    posted = next(i for i in bc.invoices.values() if i.get("orderNumber") == so["number"])
    assert posted["status"] == "Open" and posted["totalAmountIncludingTax"] == 345.0 and so["status"] == "Shipped"
    assert posted["externalDocumentNumber"] == inv.number and bc.item("TOM-5")["inventory"] == 157

    pay = await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=None, amount=D("100"), method="cash",
                                        reference=None, paid_on=None, notes=None, actor_id=None)
    assert await drain(db) == ["payment=ok"]
    line = next(iter(bc.payments.values()))
    assert line["amount"] == -100.0 and line["appliesToInvoiceId"] == posted["id"] and line["documentNumber"] == pay.number

    note = await accounts.issue_credit_note(db, t.id, inv.id, amount=D("46"), reason="2 boxes damaged")
    assert await drain(db) == ["invoice=ok"]
    memo = next(iter(bc.memos.values()))
    assert memo["status"] == "Open" and memo["invoiceId"] == posted["id"] and memo["totalAmountIncludingTax"] == 46.0
    assert memo["_lines"][0]["lineType"] == "Account" and memo["externalDocumentNumber"] == note.number

    await accounts.void_payment(db, t.id, pay.id, reason="Entered twice")
    assert await drain(db) == ["payment.void=ok"]
    assert bc.payments == {}                         # not yet posted in BC: the journal lines are removed


# ---- production checks, the same for every connector ----------------------------------------

async def test_test_connection_and_health(session, odoo):
    db = session
    t, *_ = await _business(db)
    conn, _ = await service.connect(db, t.id, provider="odoo", url="https://acme.odoo.com", database="acme",
                                    username="admin", api_key=KEY)
    result = await service.test_connection(db, conn)
    assert result["ok"] and result["warehouses"] == 2 and result["problems"] == [] and "Connected to Odoo" in result["message"]
    assert (await service.health(db, conn))["status"] == "off"

    conn = await service.activate(db, conn)
    await drain(db)
    health = await service.health(db, conn)
    assert health["status"] == "healthy", health

    odoo.down = True
    result = await service.test_connection(db, conn)
    assert not result["ok"] and result["kind"] == "unreachable"
    odoo.down = False


async def test_a_refused_login_pauses_scheduled_fetches(session, sap):
    db = session
    t, *_ = await _business(db)
    conn, _ = await _sap(db, t)
    await drain(db)
    fsap.PASSWORD, saved = "rotated", fsap.PASSWORD        # someone changed the SAP password
    try:
        await service.sync_now(db, conn)
        assert await drain(db) == ["pull=failed"]
        await db.refresh(conn)
        assert conn.settings.get(service.AUTH_FAILED)
        conn.next_pull_at = None
        await db.commit()
        assert await service.schedule_pulls(db) == 0      # no more scheduled fetches with a broken login
        health = await service.health(db, conn)
        assert health["status"] == "down" and any(c["key"] == "login" and c["status"] == "error" for c in health["checks"])
        assert "refused the login" in (await service.problems(db, conn))[0]
    finally:
        fsap.PASSWORD = saved
    assert (await service.test_connection(db, conn))["ok"]   # fixed: checking it clears the pause
    await db.refresh(conn)
    assert not conn.settings.get(service.AUTH_FAILED)
    conn.next_pull_at = None
    await db.commit()
    assert await service.schedule_pulls(db) == 1


async def test_endpoints(session, odoo, client_api):
    c, owner, t = client_api
    body = {"provider": "odoo", "url": "acme.odoo.com", "database": "acme", "username": "admin", "api_key": KEY}
    assert (await c.post("/api/v1/integrations/connect", json=body, headers=owner)).status_code == 200
    r = await c.get("/api/v1/integrations", headers=owner)
    fields = {p["key"]: p["connect_fields"] for p in r.json()["providers"]}
    assert fields["dynamics_bc"]["tenant"]["label"].startswith("Microsoft Entra") and "url" in fields["sap_b1"]
    r = await c.post("/api/v1/integrations/test", headers=owner)
    assert r.status_code == 200 and r.json()["ok"]
    r = await c.post("/api/v1/integrations/dry-run", headers=owner)
    assert r.status_code == 200 and r.json()["products"] == 3 and r.json()["branches"][0]["new"] >= 1
    r = await c.get("/api/v1/integrations/health", headers=owner)
    assert r.status_code == 200 and r.json()["status"] == "off"


@pytest_asyncio.fixture
async def client_api(session):
    import uuid as _uuid

    from app.core.security import create_access_token, hash_password
    from app.db.models.user import User
    from app.db.session import get_session
    from app.main import app

    t, *_ = await _business(session)
    u = User(tenant_id=t.id, email=f"o-{_uuid.uuid4().hex[:8]}@x.sa", role="owner", password_hash=hash_password("pw-123456"))
    session.add(u)
    await session.commit()

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c, {"Authorization": f"Bearer {create_access_token(u.id, u.tenant_id, u.role)}"}, t
    app.dependency_overrides.pop(get_session, None)
