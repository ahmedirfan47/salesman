"""Customer accounts: invoices, VAT, payments, credit notes, credit control, statements, PDFs and WhatsApp tools."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.ai import tools
from app.core.branches import default_branch
from app.core.security import create_access_token, hash_password
from app.db.models.accounts import AccountEntry, SalesInvoice
from app.db.models.customer import Customer
from app.db.models.escalation import Escalation
from app.db.models.job import Job
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.session import get_session
from app.jobs.queue import WHATSAPP_SEND_DOCUMENT
from app.main import app
from app.modules.accounts import documents
from app.modules.accounts import pdf as account_pdf
from app.modules.accounts import service as accounts
from app.modules.orders import service as orders
from app.modules.pricing import service as pricing
from app.schemas.order import OrderCreate, OrderItemIn
from app.schemas.pricing import PriceLineIn, PriceListCreate

D = Decimal


@pytest_asyncio.fixture
async def session(db):
    # production sessions don't autoflush; make sure the service never relies on it
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


async def _business(db, *, stock=100, **settings):
    t = Tenant(name="Al Rayyan Fresh", slug=f"t-{uuid.uuid4().hex[:10]}", timezone="Asia/Riyadh")
    db.add(t)
    await db.flush()
    branch = await default_branch(db, t.id)
    branch.whatsapp_phone_number_id, branch.whatsapp_access_token = f"PN-{t.id.hex[:6]}", "tok"
    await db.commit()
    pl = await pricing.create_price_list(db, t.id, PriceListCreate(lines=[
        PriceLineIn(sku="TOM-5", unit_price=D("100"), quantity=stock, currency="SAR", name_en="Tomatoes 5 kg"),
        PriceLineIn(sku="MAN-4", unit_price=D("40"), quantity=stock, currency="SAR", name_en="Mangoes 4 kg"),
    ]), branch_id=branch.id)
    await pricing.activate_price_list(db, t.id, pl.id)
    if settings:
        await accounts.update_settings(db, t.id, settings)
    return t, branch


async def _customer(db, t, branch, name="Al Noor Grocery", phone="+966500000001", **kw):
    c = Customer(tenant_id=t.id, branch_id=branch.id, name=name, whatsapp_number=phone, **kw)
    db.add(c)
    await db.commit()
    return c


async def _order(db, t, customer=None, qty=1, sku="TOM-5", **kw):
    return await orders.create_order(db, t.id, OrderCreate(
        items=[OrderItemIn(sku=sku, quantity=qty)], customer_id=customer.id if customer else None, **kw,
    ))


async def _deliver(db, t, order):
    for status_ in ("dispatched", "delivered"):
        order = await orders.transition_order(db, t.id, order.id, status_)
    return order


async def _balance(db, t, c):
    return (await accounts.account_summary(db, t.id, c))["balance"]


# --- VAT ---------------------------------------------------------------------------------------

def test_vat_is_added_per_line_when_prices_exclude_it():
    lines, subtotal, vat, total = accounts.price_lines(
        [{"sku": "A", "name": "A", "quantity": 3, "unit_price": D("33.33")}], D("15"), False)
    assert (subtotal, vat, total) == (D("99.99"), D("15.00"), D("114.99"))
    assert lines[0]["quantity"] == "3" and lines[0]["vat"] == "15.00"


def test_vat_is_extracted_when_prices_include_it():
    _, subtotal, vat, total = accounts.price_lines(
        [{"sku": "A", "name": "A", "quantity": 1, "unit_price": D("115")}], D("15"), True)
    assert (subtotal, vat, total) == (D("100.00"), D("15.00"), D("115.00"))


# --- invoices ----------------------------------------------------------------------------------

async def test_delivery_issues_one_vat_invoice_on_the_customers_account(session):
    db = session
    t, b = await _business(db, default_payment_terms_days=30)
    c = await _customer(db, t, b)
    order = await _order(db, t, c, qty=2)
    assert await accounts.invoice_for_order(db, order.id) is None  # not until delivery

    await _deliver(db, t, order)
    inv = await accounts.invoice_for_order(db, order.id)
    assert inv.number == "INV-000001" and inv.kind == "invoice" and inv.status == "open"
    assert (inv.subtotal, inv.vat_amount, inv.total) == (D("200.00"), D("30.00"), D("230.00"))
    assert inv.due_date == inv.issue_date + timedelta(days=30) and inv.currency == "SAR"
    assert inv.buyer["name"] == "Al Noor Grocery" and inv.seller["name"] == "Al Rayyan Fresh"
    assert await _balance(db, t, c) == D("230.00")

    # issuing again returns the same invoice; the number counter does not move
    again = await accounts.issue_invoice_for_order(db, await orders.get_order(db, t.id, order.id))
    assert again.id == inv.id
    order2 = await _deliver(db, t, await _order(db, t, c))
    assert (await accounts.invoice_for_order(db, order2.id)).number == "INV-000002"


async def test_invoice_on_confirmation_and_credit_note_when_cancelled(session):
    db = session
    t, b = await _business(db, invoice_on="confirmed")
    c = await _customer(db, t, b)
    order = await _order(db, t, c)
    inv = await accounts.invoice_for_order(db, order.id)
    assert inv is not None and inv.total == D("115.00")

    await orders.transition_order(db, t.id, order.id, "cancelled")
    await db.refresh(inv)
    assert inv.amount_credited == D("115.00") and inv.status == "paid" and inv.balance_due == 0
    note = await db.scalar(select(SalesInvoice).where(SalesInvoice.kind == "credit_note"))
    assert note.original_invoice_id == inv.id and note.number == "CN-000001" and note.lines == inv.lines
    assert await _balance(db, t, c) == D("0.00")


async def test_walk_in_orders_are_invoiced_but_not_on_any_account(session):
    db = session
    t, b = await _business(db)
    order = await _deliver(db, t, await _order(db, t, None, customer_name="Cash buyer", whatsapp_number="+966511111111"))
    inv = await accounts.invoice_for_order(db, order.id)
    assert inv.customer_id is None and inv.buyer["name"] == "Cash buyer"
    assert await db.scalar(select(func.count(AccountEntry.id))) == 0

    with pytest.raises(HTTPException, match="only has SAR 115.00 left"):
        await accounts.record_payment(db, t.id, customer_id=None, invoice_id=inv.id, amount=D("200"), method="cash",
                                      reference=None, paid_on=None, notes=None, actor_id=None)
    p = await accounts.record_payment(db, t.id, customer_id=None, invoice_id=inv.id, amount=D("115"), method="cash",
                                      reference=None, paid_on=None, notes=None, actor_id=None)
    await db.refresh(inv)
    assert inv.status == "paid" and p.unallocated == 0


# --- payments ----------------------------------------------------------------------------------

async def test_payments_clear_the_oldest_invoices_and_leftovers_pay_the_next_one(session):
    db = session
    t, b = await _business(db)
    c = await _customer(db, t, b)
    first = await accounts.invoice_for_order(db, (await _deliver(db, t, await _order(db, t, c))).id)
    second = await accounts.invoice_for_order(db, (await _deliver(db, t, await _order(db, t, c))).id)

    p = await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=None, amount=D("150"),
                                      method="bank_transfer", reference="TRX-1", paid_on=None, notes=None, actor_id=None)
    await db.refresh(first)
    await db.refresh(second)
    assert first.status == "paid" and second.status == "partially_paid" and second.balance_due == D("80.00")
    assert p.number == "RCPT-000001" and p.unallocated == 0

    # overpay: the extra stays on account and pays the next invoice automatically
    p2 = await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=None, amount=D("100"),
                                       method="cash", reference=None, paid_on=None, notes=None, actor_id=None)
    await db.refresh(second)
    await db.refresh(p2)
    assert second.status == "paid" and p2.unallocated == D("20.00")
    third = await accounts.invoice_for_order(db, (await _deliver(db, t, await _order(db, t, c))).id)
    await db.refresh(p2)
    assert third.amount_paid == D("20.00") and third.balance_due == D("95.00") and p2.unallocated == 0
    assert await _balance(db, t, c) == D("95.00")


async def test_a_payment_for_a_named_invoice_pays_that_one_first(session):
    db = session
    t, b = await _business(db)
    c = await _customer(db, t, b)
    first = await accounts.invoice_for_order(db, (await _deliver(db, t, await _order(db, t, c))).id)
    second = await accounts.invoice_for_order(db, (await _deliver(db, t, await _order(db, t, c))).id)
    await accounts.record_payment(db, t.id, customer_id=None, invoice_id=second.id, amount=D("115"),
                                  method="cheque", reference="CHQ 22", paid_on=None, notes=None, actor_id=None)
    await db.refresh(first)
    await db.refresh(second)
    assert second.status == "paid" and first.status == "open"


async def test_reversing_a_payment_reopens_its_invoices(session):
    db = session
    t, b = await _business(db)
    c = await _customer(db, t, b)
    inv = await accounts.invoice_for_order(db, (await _deliver(db, t, await _order(db, t, c))).id)
    p = await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=None, amount=D("115"), method="cheque",
                                      reference="CHQ 9", paid_on=None, notes=None, actor_id=None)
    await accounts.void_payment(db, t.id, p.id, reason="Cheque bounced")
    await db.refresh(inv)
    assert inv.status == "open" and inv.amount_paid == 0 and await _balance(db, t, c) == D("115.00")
    with pytest.raises(HTTPException, match="already been reversed"):
        await accounts.void_payment(db, t.id, p.id, reason="again")


async def test_payments_cannot_be_dated_in_the_future_or_be_zero(session):
    db = session
    t, b = await _business(db)
    c = await _customer(db, t, b)
    with pytest.raises(HTTPException, match="future"):
        await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=None, amount=D("10"), method="cash",
                                      reference=None, paid_on=date.today() + timedelta(days=3), notes=None, actor_id=None)
    with pytest.raises(HTTPException, match="more than zero"):
        await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=None, amount=D("0"), method="cash",
                                      reference=None, paid_on=None, notes=None, actor_id=None)


# --- credit notes ------------------------------------------------------------------------------

async def test_partial_credit_reduces_what_is_owed_and_cannot_exceed_the_invoice(session):
    db = session
    t, b = await _business(db)
    c = await _customer(db, t, b)
    inv = await accounts.invoice_for_order(db, (await _deliver(db, t, await _order(db, t, c, qty=2))).id)
    note = await accounts.issue_credit_note(db, t.id, inv.id, amount=D("46"), reason="2 boxes damaged")
    assert (note.subtotal, note.vat_amount, note.total) == (D("40.00"), D("6.00"), D("46.00"))
    await db.refresh(inv)
    assert inv.balance_due == D("184.00") and inv.status == "partially_paid"
    with pytest.raises(HTTPException, match="At most SAR 184.00"):
        await accounts.issue_credit_note(db, t.id, inv.id, amount=D("500"), reason="too much")
    assert await _balance(db, t, c) == D("184.00")


async def test_crediting_a_paid_invoice_moves_the_payment_to_the_next_invoice(session):
    db = session
    t, b = await _business(db)
    c = await _customer(db, t, b)
    first = await accounts.invoice_for_order(db, (await _deliver(db, t, await _order(db, t, c))).id)
    await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=None, amount=D("115"), method="cash",
                                  reference=None, paid_on=None, notes=None, actor_id=None)
    second = await accounts.invoice_for_order(db, (await _deliver(db, t, await _order(db, t, c))).id)
    assert second.status == "open"

    await accounts.issue_credit_note(db, t.id, first.id, amount=None, reason="Returned in full")
    await db.refresh(first)
    await db.refresh(second)
    assert first.balance_due == 0 and first.amount_paid == 0 and first.amount_credited == D("115.00")
    assert second.status == "paid"  # the freed payment now covers it
    assert await _balance(db, t, c) == D("0.00")


# --- credit control ----------------------------------------------------------------------------

async def test_orders_over_the_credit_limit_wait_for_approval(session):
    db = session
    t, b = await _business(db)
    c = await _customer(db, t, b, credit_limit=D("300"))
    await _order(db, t, c, qty=2)  # 230 incl. VAT, not invoiced yet: still counts
    held = await _order(db, t, c, qty=1)  # 230 + 115 > 300
    assert held.status == "requires_human_review"
    esc = await db.scalar(select(Escalation).where(Escalation.order_id == held.id))
    assert esc.reason_type == "credit" and esc.context["credit"][0]["type"] == "over_limit"
    assert "over its SAR 300.00 credit limit" in esc.ai_recommendation

    # the result the WhatsApp agent sees
    ctx = tools.ToolContext(tenant_id=t.id, branch_id=b.id, customer_number=c.whatsapp_number)
    res = await tools.dispatch(db, ctx, "place_order", {"items": [{"sku": "TOM-5", "quantity": 1}]})
    assert res["needs_human_review"] and res["review_reason"] == "account"

    # approving supplies it anyway
    await orders.resolve_escalation(db, t.id, esc.id, approve=True)
    assert (await orders.get_order(db, t.id, held.id)).status in ("confirmed", "preparing")


async def test_on_hold_and_overdue_customers_are_held(session):
    db = session
    t, b = await _business(db, default_payment_terms_days=0, overdue_grace_days=5)
    c = await _customer(db, t, b, on_hold=True)
    assert (await _order(db, t, c)).status == "requires_human_review"
    c.on_hold = False
    await db.commit()

    # an invoice overdue within the grace period does not block; beyond it does
    await accounts.add_opening_balance(db, t.id, c.id, amount=D("500"), as_of=date.today() - timedelta(days=3),
                                       due_date=date.today() - timedelta(days=3), note="Carried over", actor_id=None)
    assert (await _order(db, t, c)).status == "confirmed"
    await accounts.add_opening_balance(db, t.id, c.id, amount=D("50"), as_of=date.today() - timedelta(days=40),
                                       due_date=date.today() - timedelta(days=40), note="Old", actor_id=None)
    held = await _order(db, t, c)
    esc = await db.scalar(select(Escalation).where(Escalation.order_id == held.id))
    assert held.status == "requires_human_review" and esc.context["credit"][0]["type"] == "overdue"

    # switching the rule off lets orders through
    await accounts.update_settings(db, t.id, {"hold_when_overdue": False})
    assert (await _order(db, t, c)).status == "confirmed"


# --- statements and aging ----------------------------------------------------------------------

async def test_statement_has_opening_running_and_closing_balances_and_aging(session):
    db = session
    t, b = await _business(db, default_payment_terms_days=0, hold_when_overdue=False)
    c = await _customer(db, t, b)
    today = accounts.tenant_today(t)
    await accounts.add_opening_balance(db, t.id, c.id, amount=D("1000"), as_of=today - timedelta(days=100),
                                       due_date=today - timedelta(days=95), note="Opening", actor_id=None)
    await accounts.record_payment(db, t.id, customer_id=c.id, invoice_id=None, amount=D("400"), method="cash",
                                  reference=None, paid_on=today - timedelta(days=20), notes=None, actor_id=None)
    await _deliver(db, t, await _order(db, t, c))

    data = await accounts.statement(db, t.id, c, start=today - timedelta(days=30), end=today)
    assert data["opening_balance"] == D("1000.00")
    assert [ln["kind"] for ln in data["lines"]] == ["payment", "invoice"]
    assert [ln["balance"] for ln in data["lines"]] == [D("600.00"), D("715.00")]
    assert data["closing_balance"] == D("715.00") == data["summary"]["balance"]
    aging = data["summary"]["aging"]
    assert aging["days_90_plus"] == D("600.00") and aging["current"] == D("115.00")

    rows, totals = await accounts.list_accounts(db, t.id)
    assert totals["receivable"] == D("715.00") and totals["overdue"] == D("600.00") and totals["customers_overdue"] == 1


# --- PDFs --------------------------------------------------------------------------------------

async def test_invoice_and_statement_pdfs_render_with_arabic(session):
    db = session
    t, b = await _business(db, seller_name_ar="الريان للخضار", seller_vat_number="300000000000003")
    c = await _customer(db, t, b, name="بقالة النور", vat_number="310000000000003")
    inv = await accounts.invoice_for_order(db, (await _deliver(db, t, await _order(db, t, c, qty=3))).id)
    pdf = account_pdf.render_invoice_pdf(inv)
    assert pdf.startswith(b"%PDF") and b"NotoSansArabic" in pdf
    data = await accounts.statement(db, t.id, c, start=None, end=None)
    assert account_pdf.render_statement_pdf(data).startswith(b"%PDF")
    assert account_pdf.statement_filename(data).endswith(".pdf")


# --- WhatsApp agent tools ----------------------------------------------------------------------

async def test_agent_reads_only_the_callers_own_account(session):
    db = session
    t, b = await _business(db)
    mine = await _customer(db, t, b)
    other = await _customer(db, t, b, name="Al Waha", phone="+966500000002")
    my_inv = await accounts.invoice_for_order(db, (await _deliver(db, t, await _order(db, t, mine))).id)
    other_inv = await accounts.invoice_for_order(db, (await _deliver(db, t, await _order(db, t, other))).id)

    ctx = tools.ToolContext(tenant_id=t.id, branch_id=b.id, customer_number="966500000001")
    acct = await tools.dispatch(db, ctx, "get_my_account", {})
    assert acct["registered"] and acct["balance_owed"] == 115.0
    assert [i["number"] for i in acct["unpaid_invoices"]] == [my_inv.number]

    assert (await tools.dispatch(db, ctx, "send_invoice_copy", {"invoice_number": other_inv.number}))["sent"] is False
    sent = await tools.dispatch(db, ctx, "send_invoice_copy", {"invoice_number": my_inv.number.lower(), "language": "ar"})
    assert sent["sent"] is True
    stmt = await tools.dispatch(db, ctx, "send_my_statement", {"months": 2})
    assert stmt["sent"] is True
    jobs = list(await db.scalars(select(Job).where(Job.kind == WHATSAPP_SEND_DOCUMENT).order_by(Job.created_at)))
    assert [j.payload["doc"] for j in jobs] == ["invoice", "statement"]

    content, filename, caption = await documents.build(db, jobs[0].payload)
    assert content.startswith(b"%PDF") and filename == f"{my_inv.number}.pdf" and my_inv.number in caption
    content, filename, caption = await documents.build(db, jobs[1].payload)
    assert content.startswith(b"%PDF") and "Balance due: SAR 115.00" in caption

    stranger = tools.ToolContext(tenant_id=t.id, branch_id=b.id, customer_number="+966599999999")
    assert (await tools.dispatch(db, stranger, "get_my_account", {}))["registered"] is False


# --- API and permissions -----------------------------------------------------------------------

async def _user(db, t, role, branch=None):
    u = User(tenant_id=t.id, email=f"{role}-{uuid.uuid4().hex[:6]}@x.co", role=role,
             password_hash=hash_password("pw-123456"), branch_id=branch.id if branch else None)
    db.add(u)
    await db.commit()
    return u


def _auth(u):
    return {"Authorization": f"Bearer {create_access_token(u.id, u.tenant_id, u.role)}"}


async def test_api_end_to_end_with_permissions(session, client):
    db = session
    t, b = await _business(db)
    c = await _customer(db, t, b)
    owner, rep, driver = await _user(db, t, "owner"), await _user(db, t, "salesman", b), await _user(db, t, "driver", b)
    order = await _deliver(db, t, await _order(db, t, c))

    r = await client.get("/api/v1/accounts", headers=_auth(rep))
    assert r.status_code == 200 and r.json()["customers"][0]["balance"] == "115.00"
    assert (await client.get("/api/v1/accounts", headers=_auth(driver))).status_code == 403

    inv = (await client.get(f"/api/v1/accounts/orders/{order.id}/invoice", headers=_auth(rep))).json()
    assert inv["number"] == "INV-000001" and inv["lines"][0]["vat"] == "15.00"

    pay = {"customer_id": str(c.id), "amount": "100", "method": "bank_transfer", "reference": "T-1"}
    assert (await client.post("/api/v1/accounts/payments", json=pay, headers=_auth(rep))).status_code == 403
    r = await client.post("/api/v1/accounts/payments", json=pay, headers=_auth(owner))
    assert r.status_code == 201 and r.json()["number"] == "RCPT-000001"

    r = await client.patch(f"/api/v1/accounts/customers/{c.id}/credit",
                           json={"credit_limit": "5000", "payment_terms_days": 15, "vat_number": "310000000000003"},
                           headers=_auth(owner))
    assert r.status_code == 200 and r.json()["credit_limit"] == "5000.00" and r.json()["available_credit"] == "4985.00"
    detail = (await client.get(f"/api/v1/accounts/customers/{c.id}", headers=_auth(owner))).json()
    assert detail["own_payment_terms_days"] == 15 and detail["vat_number"] == "310000000000003"
    assert detail["account"]["balance"] == "15.00" and len(detail["payments"]) == 1

    # back to the business default limit
    r = await client.patch(f"/api/v1/accounts/customers/{c.id}/credit", json={"credit_limit": None}, headers=_auth(owner))
    assert r.json()["credit_limit"] is None

    st = (await client.get(f"/api/v1/accounts/customers/{c.id}/statement", headers=_auth(rep))).json()
    assert st["closing_balance"] == "15.00" and len(st["lines"]) == 2
    for path in (f"/api/v1/accounts/customers/{c.id}/statement/pdf", f"/api/v1/accounts/invoices/{inv['id']}/pdf"):
        r = await client.get(path, headers=_auth(rep))
        assert r.status_code == 200 and r.content.startswith(b"%PDF")

    r = await client.post(f"/api/v1/accounts/invoices/{inv['id']}/credit-note", json={"reason": "Wrong price"},
                          headers=_auth(owner))
    assert r.status_code == 201 and r.json()["kind"] == "credit_note"
    unpaid = (await client.get("/api/v1/accounts/invoices?status=unpaid", headers=_auth(owner))).json()
    assert unpaid == []

    settings = (await client.put("/api/v1/accounts/settings", json={"seller_vat_number": "300000000000003",
                                                                     "default_payment_terms_days": 45},
                                 headers=_auth(owner))).json()
    assert settings["seller_vat_number"] == "300000000000003" and settings["default_payment_terms_days"] == 45
    assert (await client.put("/api/v1/accounts/settings", json={"vat_rate": "5"}, headers=_auth(rep))).status_code == 403

    # the customers list shows the credit fields read-only
    cust = (await client.get("/api/v1/customers", headers=_auth(owner))).json()[0]
    assert cust["vat_number"] == "310000000000003" and cust["on_hold"] is False


async def test_order_invoice_can_be_issued_early_from_the_dashboard(session, client):
    db = session
    t, b = await _business(db)
    c = await _customer(db, t, b)
    owner = await _user(db, t, "owner")
    order = await _order(db, t, c)
    r = await client.post(f"/api/v1/accounts/orders/{order.id}/invoice", headers=_auth(owner))
    assert r.status_code == 201 and r.json()["status"] == "open"
    await _deliver(db, t, order)  # delivery does not issue a second one
    assert await db.scalar(select(func.count(SalesInvoice.id)).where(SalesInvoice.order_id == order.id)) == 1

    held = await _order(db, t, c, qty=1000)  # short on stock: held, can't be invoiced
    r = await client.post(f"/api/v1/accounts/orders/{held.id}/invoice", headers=_auth(owner))
    assert r.status_code == 409


async def test_orders_delivered_before_accounts_existed_do_not_count_against_credit(session):
    db = session
    t, b = await _business(db)
    c = await _customer(db, t, b)
    old = await _order(db, t, c, qty=5)
    old.status = "completed"  # delivered long ago, never invoiced
    await db.commit()
    c.credit_limit = D("200")
    await db.commit()
    summary = await accounts.account_summary(db, t.id, c)
    assert summary["uninvoiced"] == 0 and summary["exposure"] == 0
    assert (await _order(db, t, c)).status == "confirmed"  # 115 fits under 200