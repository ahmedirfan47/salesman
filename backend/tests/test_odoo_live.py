"""End-to-end check against a real Odoo server. Skipped unless these are set:

    ODOO_TEST_URL   e.g. https://mycompany.odoo.com
    ODOO_TEST_DB    database name
    ODOO_TEST_USER  login of the API key's user (needed for Odoo 18 and older)
    ODOO_TEST_KEY   API key
    ODOO_TEST_API   optional: json2 or jsonrpc, to force one

The Odoo database needs Sales, Inventory and Invoicing, a sales tax matching
the VAT rate, a sales journal, a bank or cash journal, and at least one
stock-tracked product with an Internal Reference and 2+ units in stock.
For an Odoo on your own machine (http://localhost...), also set
ERP_ALLOW_PRIVATE_URLS=true. It writes real records (a customer, a sales order, an invoice, a payment, a
credit note) -- use a test database.
"""
import os
import random
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.branches import default_branch
from app.db.models.customer import Customer
from app.db.models.integration import IntegrationEvent
from app.db.models.inventory import Inventory
from app.db.models.job import Job
from app.db.models.product import Product
from app.db.models.tenant import Tenant
from app.jobs.queue import ERP_PULL, ERP_PUSH
from app.modules.accounts import service as accounts
from app.modules.integrations import service
from app.modules.orders import service as orders
from app.modules.pricing import service as pricing
from app.schemas.order import OrderCreate, OrderItemIn

URL, DB, USER, KEY = (os.getenv(k) for k in ("ODOO_TEST_URL", "ODOO_TEST_DB", "ODOO_TEST_USER", "ODOO_TEST_KEY"))
pytestmark = pytest.mark.skipif(not (URL and KEY), reason="set ODOO_TEST_URL and ODOO_TEST_KEY to run against a real Odoo")


@pytest_asyncio.fixture
async def session(db):
    db.sync_session.autoflush = False
    yield db


async def drain(db) -> list[str]:
    """Run queued ERP jobs in order, the way the worker would."""
    results = []
    while True:
        job = await db.scalar(select(Job).where(Job.kind.in_((ERP_PUSH, ERP_PULL)), Job.status == "queued")
                              .order_by(Job.run_after, Job.created_at).limit(1))
        if job is None:
            return results
        job.status = "done"
        await db.commit()
        run = service.run_push if job.kind == ERP_PUSH else service.run_pull
        results.append(f"{job.payload.get('action', 'pull')}={await run(db, job.payload)}")


async def events(db) -> dict[str, IntegrationEvent]:
    return {f"{e.action}:{e.label}": e for e in await db.scalars(select(IntegrationEvent))}


async def test_full_flow_against_a_real_odoo(session):
    db = session
    t = Tenant(name="Salesman Live Test", slug=f"live-{uuid.uuid4().hex[:8]}", timezone="Asia/Riyadh")
    db.add(t)
    await db.flush()
    branch = await default_branch(db, t.id)
    await db.commit()
    await accounts.update_settings(db, t.id, {"currency": "SAR", "vat_rate": Decimal("15"), "prices_include_vat": False,
                                              "invoice_on": "delivered", "default_payment_terms_days": 30})
    vat = "3" + "".join(random.choices("0123456789", k=13)) + "3"
    phone = "+9665" + "".join(random.choices("0123456789", k=8))
    customer = Customer(tenant_id=t.id, branch_id=branch.id, name="Live Test Grocery", company="Live Test Grocery LLC",
                        whatsapp_number=phone, vat_number=vat, cr_number="1010" + "".join(random.choices("0123456789", k=6)),
                        street="Olaya Street", building_number="1234", district="Al Olaya", city="Riyadh", postal_code="12241")
    db.add(customer)
    await db.commit()

    # 1. connect: the first mapping is complete
    conn, options = await service.connect(db, t.id, provider="odoo", url=URL, database=DB, username=USER, api_key=KEY)
    if os.getenv("ODOO_TEST_API"):
        conn.api = os.getenv("ODOO_TEST_API")
        await db.commit()
    print("Odoo", conn.server_version, "over", conn.api)
    assert await service.problems(db, conn, options) == []

    # 2. switch on: prices and stock come from Odoo
    conn = await service.activate(db, conn)
    print(await drain(db))
    ev = await events(db)
    pull = next(e for e in ev.values() if e.action == "catalog")
    assert pull.status in ("ok", "warning"), pull.message
    print("pull:", pull.message)
    for plist in await pricing.list_price_lists(db, t.id, branch.id):
        assert plist.source_filename == "Odoo sync"
    stocked = None
    for product, inv in await db.execute(select(Product, Inventory).join(Inventory, Inventory.product_id == Product.id)
                                         .where(Inventory.branch_id == branch.id, Inventory.quantity_on_hand >= 2)):
        price = await pricing.get_current_price(db, t.id, product.sku, branch.id)
        if price and price["unit_price"] > 0:
            stocked = product
            break
    assert stocked is not None, "Odoo needs a stock-tracked product with 2+ units in the mapped warehouse"
    before = (await pricing.get_current_price(db, t.id, stocked.sku, branch.id))["quantity_on_hand"]

    # 3. an order: a confirmed sales order in Odoo, stock reserved there
    order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku=stocked.sku, quantity=2)], customer_id=customer.id))
    assert order.status == "confirmed"
    print(await drain(db))
    ev = await events(db)
    so = ev[f"order.confirmed:{order.order_number}"]
    assert so.status == "ok", so.message
    print("sales order", so.external_ref)

    # the next fetch does not hand the reserved units back
    await service.sync_now(db, conn)
    print(await drain(db))
    after = (await pricing.get_current_price(db, t.id, stocked.sku, branch.id))["quantity_on_hand"]
    assert after == before - 2, (before, after)

    # 4. delivered: the delivery is validated and the invoice is posted, linked to the sales order
    order = await orders.transition_order(db, t.id, order.id, "dispatched")
    order = await orders.transition_order(db, t.id, order.id, "delivered")
    inv = await accounts.invoice_for_order(db, order.id)
    print(await drain(db))
    ev = await events(db)
    assert ev[f"order.delivered:{order.order_number}"].status in ("ok", "warning"), ev[f"order.delivered:{order.order_number}"].message
    invoice_event = ev[f"invoice:{inv.number}"]
    assert invoice_event.status == "ok", invoice_event.message
    print("invoice", invoice_event.external_ref, "delivery:", ev[f"order.delivered:{order.order_number}"].external_ref)

    # 5. part payment, matched to the invoice
    pay = await accounts.record_payment(db, t.id, customer_id=customer.id, invoice_id=None, amount=Decimal("50"),
                                        method="bank_transfer", reference="LIVE-1", paid_on=None, notes=None, actor_id=None)
    print(await drain(db))
    ev = await events(db)
    assert ev[f"payment:{pay.number}"].status == "ok", ev[f"payment:{pay.number}"].message

    # 6. a partial credit note, matched to the invoice
    note = await accounts.issue_credit_note(db, t.id, inv.id, amount=Decimal("23"), reason="One box damaged")
    print(await drain(db))
    ev = await events(db)
    assert ev[f"invoice:{note.number}"].status == "ok", ev[f"invoice:{note.number}"].message

    rows = await service.balances(db, conn)
    mine = next(r for r in rows if r["customer_id"] == customer.id)
    print("balance", mine)
    assert mine["difference"] == 0

    # 7. the payment bounces: cancelled in Odoo, balances still agree
    await accounts.void_payment(db, t.id, pay.id, reason="Bounced")
    print(await drain(db))
    ev = await events(db)
    assert ev[f"payment.void:{pay.number}"].status == "ok", ev[f"payment.void:{pay.number}"].message
    mine = next(r for r in await service.balances(db, conn) if r["customer_id"] == customer.id)
    print("balance after reversal", mine)
    assert mine["difference"] == 0

    # 8. retrying something already sent never duplicates it
    await service.retry(db, conn, invoice_event.id)
    print(await drain(db))
    mine = next(r for r in await service.balances(db, conn) if r["customer_id"] == customer.id)
    assert mine["difference"] == 0