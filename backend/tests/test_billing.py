"""Billing: subscriptions, setup and monthly invoices, read-only mode, the Stonic console, PDFs."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import settings
from app.core.branches import default_branch
from app.core.security import create_access_token, hash_password
from app.db.models.billing import Invoice
from app.db.models.branch import Branch
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.session import get_session
from app.main import app
from app.modules.billing import service as billing
from app.modules.billing.pdf import render_invoice_pdf

ADMIN_EMAIL = "ops@stonic-hq.com"


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture(autouse=True)
def _platform_admin(monkeypatch):
    monkeypatch.setattr(settings, "PLATFORM_ADMIN_EMAILS", f"{ADMIN_EMAIL}, other@stonic-hq.com")
    monkeypatch.setattr(settings, "BILLING_BANK_DETAILS", "Bank: Test Bank | IBAN: SA00 0000 0000 0000")


async def _tenant(db, name="Al Rayyan Fresh", branches=1):
    t = Tenant(name=name, slug=f"t-{uuid.uuid4().hex[:10]}")
    db.add(t)
    await db.flush()
    await default_branch(db, t.id)
    for i in range(branches - 1):
        db.add(Branch(tenant_id=t.id, name=f"Branch {i + 2}", is_default=False, is_active=True,
                      order_updates_enabled=True))
    await db.commit()
    return t


async def _user(db, tenant, role, email=None):
    u = User(tenant_id=tenant.id, email=email or f"{role}-{uuid.uuid4().hex[:6]}@x.co",
             password_hash=hash_password("pw-123456"), role=role)
    db.add(u)
    await db.commit()
    return u


def _auth(u):
    return {"Authorization": f"Bearer {create_access_token(u.id, u.tenant_id, u.role)}"}


# --- dates and money ---------------------------------------------------------------------

def test_add_months_keeps_the_day_or_uses_the_last_day():
    assert billing.add_months(date(2026, 1, 31)) == date(2026, 2, 28)
    assert billing.add_months(date(2026, 11, 15)) == date(2026, 12, 15)
    assert billing.add_months(date(2026, 12, 1)) == date(2027, 1, 1)


# --- setup invoices -----------------------------------------------------------------------

async def test_setup_fee_is_invoiced_once_per_branch(db):
    t = await _tenant(db, branches=2)
    await billing.upsert_subscription(db, t.id, {"next_invoice_on": date(2026, 11, 1)}, on=date(2026, 10, 26))

    inv = await billing.issue_setup_invoice(db, t.id, on=date(2026, 10, 26))
    assert inv.kind == "setup" and inv.total == Decimal("22000.00") and inv.currency == "USD"
    assert inv.lines[0]["quantity"] == "2" and inv.due_on == date(2026, 11, 9)
    assert inv.number == "INV-2026-00001" and inv.bill_to["name"] == "Al Rayyan Fresh"
    with pytest.raises(Exception, match="already invoiced"):
        await billing.issue_setup_invoice(db, t.id, on=date(2026, 10, 26))

    # a third branch opens: only that one owes setup
    db.add(Branch(tenant_id=t.id, name="Dammam", is_default=False, is_active=True, order_updates_enabled=True))
    await db.commit()
    third = await billing.issue_setup_invoice(db, t.id, on=date(2026, 10, 27))
    assert third.total == Decimal("11000.00") and third.number == "INV-2026-00002"

    # voiding it makes that branch owe setup again
    await billing.void(db, third.id, "Wrong branch count")
    sub = await billing.get_subscription(db, t.id)
    assert await billing.unbilled_setup_branches(db, t.id, sub) == 1


# --- monthly invoices ----------------------------------------------------------------------

async def test_monthly_invoices_are_issued_on_their_date_and_never_twice(db):
    t = await _tenant(db, branches=2)
    await billing.upsert_subscription(db, t.id, {"next_invoice_on": date(2026, 11, 1), "tax_percent": Decimal("15")})

    assert await billing.issue_due_invoices(db, on=date(2026, 10, 31)) == 0
    assert await billing.issue_due_invoices(db, on=date(2026, 11, 1)) == 1
    assert await billing.issue_due_invoices(db, on=date(2026, 11, 1)) == 0

    inv = await db.scalar(select(Invoice).where(Invoice.kind == "subscription"))
    assert (inv.period_start, inv.period_end) == (date(2026, 11, 1), date(2026, 11, 30))
    assert inv.subtotal == Decimal("2100.00") and inv.tax_amount == Decimal("315.00") and inv.total == Decimal("2415.00")
    assert "2 branches" in inv.lines[0]["description"]
    sub = await billing.get_subscription(db, t.id)
    assert sub.next_invoice_on == date(2026, 12, 1)


async def test_missed_months_are_caught_up_and_paused_subscriptions_skipped(db):
    t = await _tenant(db)
    paused = await _tenant(db, "Paused Co")
    await billing.upsert_subscription(db, t.id, {"next_invoice_on": date(2026, 11, 1)})
    await billing.upsert_subscription(db, paused.id, {"next_invoice_on": date(2026, 11, 1), "status": "paused"})

    assert await billing.issue_due_invoices(db, on=date(2027, 1, 15)) == 3  # Nov, Dec, Jan
    periods = list(await db.scalars(select(Invoice.period_start).where(Invoice.tenant_id == t.id).order_by(Invoice.period_start)))
    assert periods == [date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1)]
    assert await db.scalar(select(func.count(Invoice.id)).where(Invoice.tenant_id == paused.id)) == 0


async def test_worker_sweep_issues_due_invoices(db):
    from app.jobs import worker

    t = await _tenant(db)
    await billing.upsert_subscription(db, t.id, {"next_invoice_on": billing.today()})

    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    await worker.sweep(lambda: _Ctx())
    assert await db.scalar(select(func.count(Invoice.id))) == 1


# --- account state --------------------------------------------------------------------------

async def test_account_state_moves_from_open_to_overdue_to_read_only(db):
    t = await _tenant(db)
    await billing.upsert_subscription(db, t.id, {"next_invoice_on": date(2026, 11, 1), "payment_terms_days": 10,
                                                 "grace_days": 14})
    await billing.issue_due_invoices(db, on=date(2026, 11, 1))  # due 11 Nov, read-only from 26 Nov

    assert (await billing.account_state(db, t.id, on=date(2026, 11, 5)))["state"] == "open"
    overdue = await billing.account_state(db, t.id, on=date(2026, 11, 12))
    assert overdue["state"] == "overdue" and overdue["read_only_from"] == date(2026, 11, 26)
    assert "becomes read-only on 26 Nov 2026" in billing.state_message(overdue, admin=True)
    assert billing.state_message(overdue, admin=False) is None
    assert await billing.is_read_only(db, t.id, on=date(2026, 11, 25)) is False
    assert await billing.is_read_only(db, t.id, on=date(2026, 11, 26)) is True
    ro = await billing.account_state(db, t.id, on=date(2026, 11, 26))
    assert ro["state"] == "read_only" and ro["outstanding"] == ro["overdue"] == Decimal("1050.00")
    assert "Pay the overdue USD 1,050.00" in billing.state_message(ro, admin=True)

    inv = await db.scalar(select(Invoice))
    await billing.mark_paid(db, inv.id, reference="TT-123")
    assert (await billing.account_state(db, t.id, on=date(2026, 11, 26)))["state"] == "ok"


async def _overdue_tenant(db, *, days_late=30):
    t = await _tenant(db)
    await billing.upsert_subscription(db, t.id, {"next_invoice_on": billing.today() - timedelta(days=days_late + 14)})
    inv = await billing.issue_next_monthly(db, t.id, on=billing.today() - timedelta(days=days_late + 14))
    return t, inv


async def test_overdue_account_is_read_only_until_paid(db, client):
    t, inv = await _overdue_tenant(db)
    owner = await _user(db, t, "owner")
    driver = await _user(db, t, "driver")
    stonic = await _tenant(db, "Stonic")
    ops = await _user(db, stonic, "owner", email=ADMIN_EMAIL)

    # reading still works; changing anything is refused with 402
    assert (await client.get("/api/v1/orders", headers=_auth(owner))).status_code == 200
    r = await client.post("/api/v1/products", headers=_auth(owner), json={"sku": "X-1", "name_en": "X"})
    assert r.status_code == 402 and "read-only" in r.json()["detail"]

    me = (await client.get("/api/v1/auth/me", headers=_auth(owner))).json()
    assert me["billing_state"] == "read_only" and inv.number in me["billing_message"]
    staff = (await client.get("/api/v1/auth/me", headers=_auth(driver))).json()
    assert "contact your administrator" in staff["billing_message"] and inv.number not in staff["billing_message"]

    r = await client.post(f"/api/v1/platform/invoices/{inv.id}/paid", headers=_auth(ops), json={"reference": "SNB 4471"})
    assert r.status_code == 200 and r.json()["status"] == "paid"
    r = await client.post("/api/v1/products", headers=_auth(owner), json={"sku": "X-1", "name_en": "X"})
    assert r.status_code == 201


async def test_platform_admin_is_never_blocked(db, client):
    t, _ = await _overdue_tenant(db)
    ops = await _user(db, t, "owner", email=ADMIN_EMAIL)
    r = await client.post("/api/v1/products", headers=_auth(ops), json={"sku": "X-2", "name_en": "X"})
    assert r.status_code == 201


# --- the business's billing page ------------------------------------------------------------

async def test_billing_page_shows_invoices_and_bank_details(db, client):
    t = await _tenant(db, branches=2)
    owner = await _user(db, t, "owner")
    salesman = await _user(db, t, "salesman")

    r = (await client.get("/api/v1/billing", headers=_auth(owner))).json()
    assert r["subscription"] is None and r["invoices"] == [] and r["account"]["state"] == "ok"

    await billing.upsert_subscription(db, t.id, {"next_invoice_on": billing.today()})
    r = (await client.get("/api/v1/billing", headers=_auth(owner))).json()  # issues today's invoice on the way
    assert len(r["invoices"]) == 1 and r["invoices"][0]["total"] == "2100.00"
    assert r["account"]["state"] == "open" and r["active_branches"] == 2 and r["unbilled_setup_branches"] == 2
    assert r["pay_to"]["bank_details"] == ["Bank: Test Bank", "IBAN: SA00 0000 0000 0000"]

    pdf = await client.get(f"/api/v1/billing/invoices/{r['invoices'][0]['id']}/pdf", headers=_auth(owner))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert (await client.get("/api/v1/billing", headers=_auth(salesman))).status_code == 403

    other = await _tenant(db, "Other Co")
    stranger = await _user(db, other, "owner")
    r = await client.get(f"/api/v1/billing/invoices/{r['invoices'][0]['id']}/pdf", headers=_auth(stranger))
    assert r.status_code == 404


# --- Stonic console -----------------------------------------------------------------------------

async def test_console_is_hidden_from_everyone_else(db, client):
    t = await _tenant(db)
    owner = await _user(db, t, "owner")
    assert (await client.get("/api/v1/platform/tenants", headers=_auth(owner))).status_code == 404
    me = (await client.get("/api/v1/auth/me", headers=_auth(owner))).json()
    assert me["is_platform_admin"] is False


async def test_console_sets_up_and_bills_a_business(db, client):
    stonic = await _tenant(db, "Stonic")
    ops = await _user(db, stonic, "owner", email=ADMIN_EMAIL)
    customer = await _tenant(db, "Al Rayyan Fresh", branches=3)
    h = _auth(ops)
    assert (await client.get("/api/v1/auth/me", headers=h)).json()["is_platform_admin"] is True

    r = await client.put(f"/api/v1/platform/tenants/{customer.id}/subscription", headers=h, json={
        "next_invoice_on": str(billing.today() + timedelta(days=5)), "billing_name": "Al Rayyan Fresh Trading Co.",
        "billing_tax_id": "300000000000003", "tax_percent": "15", "currency": "sar",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subscription"]["currency"] == "SAR" and body["unbilled_setup_branches"] == 3

    setup = await client.post(f"/api/v1/platform/tenants/{customer.id}/invoices/setup", headers=h, json={})
    assert setup.status_code == 201 and setup.json()["total"] == "37950.00"  # 3 x 11,000 + 15% VAT
    nxt = await client.post(f"/api/v1/platform/tenants/{customer.id}/invoices/next", headers=h)
    assert nxt.status_code == 201 and nxt.json()["kind"] == "subscription"
    custom = await client.post(f"/api/v1/platform/tenants/{customer.id}/invoices", headers=h, json={
        "lines": [{"description": "Extra WhatsApp number set-up", "quantity": "1", "unit_amount": "500"}],
        "notes": "Agreed on the call of 20 Oct",
    })
    assert custom.status_code == 201 and custom.json()["bill_to"]["tax_id"] == "300000000000003"

    rows = (await client.get("/api/v1/platform/tenants", headers=h)).json()
    row = next(x for x in rows if x["id"] == str(customer.id))
    assert row["account"]["open_invoices"] == 3 and row["unbilled_setup_branches"] == 0

    inv_id = setup.json()["id"]
    assert (await client.post(f"/api/v1/platform/invoices/{inv_id}/void", headers=h,
                              json={"reason": "x"})).status_code == 200
    assert (await client.post(f"/api/v1/platform/invoices/{inv_id}/paid", headers=h, json={})).status_code == 409
    paid = await client.post(f"/api/v1/platform/invoices/{custom.json()['id']}/paid", headers=h,
                             json={"paid_on": str(billing.today()), "reference": "TT-9"})
    assert paid.json()["payment_reference"] == "TT-9"
    reopened = await client.post(f"/api/v1/platform/invoices/{custom.json()['id']}/reopen", headers=h)
    assert reopened.json()["status"] == "open" and reopened.json()["paid_on"] is None

    pdf = await client.get(f"/api/v1/platform/invoices/{nxt.json()['id']}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    detail = (await client.get(f"/api/v1/platform/tenants/{customer.id}", headers=h)).json()
    assert [i["status"] for i in detail["invoices"]].count("void") == 1

    run = await client.post("/api/v1/platform/billing/run", headers=h)
    assert run.status_code == 200 and run.json()["issued"] == 0


def test_invoice_pdf_renders_arabic_names_without_crashing():
    inv = Invoice(
        number="INV-2026-00099", kind="setup", status="paid", currency="SAR",
        lines=[{"description": "إعداد الفرع", "quantity": "1", "unit_amount": "11000.00", "amount": "11000.00"}],
        subtotal=Decimal("11000"), tax_percent=Decimal("15"), tax_amount=Decimal("1650"), total=Decimal("12650"),
        bill_to={"name": "مؤسسة الريان", "address": "Riyadh | KSA"}, issued_on=date(2026, 10, 1),
        due_on=date(2026, 10, 15), paid_on=date(2026, 10, 3), payment_reference="TT-1", notes="Thank you",
    )
    assert render_invoice_pdf(inv).startswith(b"%PDF")


async def test_moving_the_invoice_date_back_never_bills_a_period_twice(db):
    t = await _tenant(db)
    await billing.upsert_subscription(db, t.id, {"next_invoice_on": date(2026, 11, 1)})
    assert await billing.issue_due_invoices(db, on=date(2026, 12, 5)) == 2  # Nov, Dec
    await billing.upsert_subscription(db, t.id, {"next_invoice_on": date(2026, 11, 1)})
    assert await billing.issue_due_invoices(db, on=date(2026, 12, 5)) == 0
    inv = await billing.issue_next_monthly(db, t.id, on=date(2026, 12, 5))
    assert inv.period_start == date(2027, 1, 1)