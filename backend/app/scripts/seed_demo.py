"""Create (or reset) a read-only demo account with realistic sample data.

    python -m app.scripts.seed_demo --email demo@yourdomain.com --password 'a-strong-password'
    python -m app.scripts.seed_demo --email demo@yourdomain.com --password '...' --reset

The demo user has the 'demo' role: it can open every screen (orders,
analytics, conversations, zones, team...) but the API rejects every change.
All data lives in its own tenant, so it never touches a real customer's data.
The demo business has two branches, Riyadh and Jeddah, each with its own
prices, stock, zones, drivers and customers.
--reset deletes that demo tenant and rebuilds it with fresh dates.
"""
import argparse
import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.core.security import hash_password
from app.db.models.accounts import (
    AccountEntry, AccountSettings, CustomerPayment, DocumentCounter, PaymentAllocation, SalesInvoice,
)
from app.db.models.branch import Branch
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.escalation import Escalation
from app.db.models.inventory import Inventory
from app.db.models.inventory_transaction import InventoryTransaction
from app.db.models.job import Job
from app.db.models.message import Message
from app.db.models.order import Order
from app.db.models.order_event import OrderEvent
from app.db.models.order_item import OrderItem
from app.db.models.price_list import PriceList
from app.db.models.print_job import PrintJob
from app.db.models.product import Product
from app.db.models.product_price import ProductPrice
from app.db.models.prospect import Prospect, ProspectActivity
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.models.zatca import ZatcaDocument, ZatcaUnit
from app.db.models.zone import DriverZone, Zone

DEMO_SLUG = "salesman-demo"
DEMO_NAME = "Demo — Fresh Produce Wholesale"
CURRENCY = "SAR"

# sku, English, Arabic, price, cost (None = not entered yet), stock
PRODUCTS = [
    ("TOM-5", "Tomatoes 5 kg", "طماطم ٥ كجم", "35.00", "24.50", 182),
    ("POT-10", "Potatoes 10 kg", "بطاطس ١٠ كجم", "22.00", "15.00", 125),
    ("CUC-5", "Cucumbers 5 kg", "خيار ٥ كجم", "28.00", "19.00", 96),
    ("ORA-8", "Oranges 8 kg", "برتقال ٨ كجم", "42.00", "31.00", 74),
    ("MAN-4", "Mangoes 4 kg", "مانجو ٤ كجم", "48.00", None, 32),
    ("ONI-10", "Onions 10 kg", "بصل ١٠ كجم", "18.00", None, 8),
]
ZONES = ["Riyadh North", "Riyadh East", "Riyadh Central", "Riyadh West"]
DRIVERS = [("Faisal", "Riyadh North"), ("Omar", "Riyadh East"), ("Saad", "Riyadh Central")]
# name, zone, typical days between orders
CUSTOMERS = [
    ("Al Noor Grocery", "Riyadh North", 3),
    ("Al Waha Market", "Riyadh East", 5),
    ("Hayat Minimarket", "Riyadh North", 4),
    ("Green Valley Store", "Riyadh Central", 4),
    ("Al Safa Supermarket", "Riyadh West", 6),
    ("Riyadh Fresh Mart", "Riyadh Central", 7),
    ("Bait Al Khair", "Riyadh East", 5),
]
# customers who used to order often and have gone quiet (shown under "Customers going quiet")
QUIET = {"Al Waha Market": 26, "Green Valley Store": 21}

FLOW = ["confirmed", "preparing", "dispatched", "delivered", "completed"]


async def _wipe(db: AsyncSession) -> None:
    tenant = await db.scalar(select(Tenant).where(Tenant.slug == DEMO_SLUG))
    if tenant is None:
        return
    tid = tenant.id
    # e-invoices, then customer accounts: they reference orders, customers and each other
    await db.execute(update(ZatcaDocument).where(ZatcaDocument.tenant_id == tid).values(replaced_by_id=None))
    for model in (ZatcaDocument, ZatcaUnit):
        await db.execute(delete(model).where(model.tenant_id == tid))
    await db.execute(update(SalesInvoice).where(SalesInvoice.tenant_id == tid).values(original_invoice_id=None))
    for model in (PaymentAllocation, AccountEntry, CustomerPayment, SalesInvoice, DocumentCounter, AccountSettings):
        await db.execute(delete(model).where(model.tenant_id == tid))
    # children first (some FKs are RESTRICT), then the tenant
    for model in (ProspectActivity, Prospect, Job, Message, Conversation, Escalation, PrintJob,
                  OrderEvent, OrderItem, Order, DriverZone, Customer, InventoryTransaction, Inventory,
                  ProductPrice, PriceList, Product, Zone):
        await db.execute(delete(model).where(model.tenant_id == tid))
    await db.execute(delete(User).where(User.tenant_id == tid))
    await db.execute(delete(Tenant).where(Tenant.id == tid))
    await db.commit()


async def seed(db: AsyncSession, email: str, password: str, *, reset: bool = False) -> Tenant:
    rng = random.Random(14)
    now = datetime.now(timezone.utc)

    existing = await db.scalar(select(Tenant).where(Tenant.slug == DEMO_SLUG))
    if existing and not reset:
        raise SystemExit("The demo tenant already exists. Re-run with --reset to rebuild it.")
    await _wipe(db)

    other = await db.scalar(select(User).where(User.email == email))
    if other is not None:
        raise SystemExit(f"{email} is already used by another account. Choose a different demo email.")

    tenant = Tenant(name=DEMO_NAME, slug=DEMO_SLUG, timezone="Asia/Riyadh")
    db.add(tenant)
    await db.flush()
    tid = tenant.id

    riyadh = Branch(tenant_id=tid, name="Riyadh", city="Riyadh", address="Al Aziziyah wholesale market",
                    is_default=True, is_active=True, order_updates_enabled=True)
    jeddah = Branch(tenant_id=tid, name="Jeddah", city="Jeddah", address="Al Haramain Rd, central market",
                    is_default=False, is_active=True, order_updates_enabled=True)
    db.add_all([riyadh, jeddah])
    await db.flush()
    rid = riyadh.id

    demo_user = User(tenant_id=tid, email=email, password_hash=hash_password(password),
                     full_name="Demo viewer", role=UserRole.DEMO.value)
    db.add(demo_user)
    rep = User(tenant_id=tid, branch_id=rid, email=f"nasser.demo.{uuid.uuid4().hex[:6]}@example.com",
               password_hash=hash_password(uuid.uuid4().hex), full_name="Nasser", role=UserRole.SALESMAN.value)
    db.add(rep)

    zones = {}
    for name in ZONES:
        z = Zone(tenant_id=tid, branch_id=rid, name=name, description=f"{name} delivery area")
        db.add(z)
        zones[name] = z
    await db.flush()

    drivers = {}
    for name, zone_name in DRIVERS:
        d = User(tenant_id=tid, branch_id=rid, email=f"{name.lower()}.demo.{uuid.uuid4().hex[:6]}@example.com",
                 password_hash=hash_password(uuid.uuid4().hex), full_name=name, role=UserRole.DRIVER.value)
        db.add(d)
        await db.flush()
        db.add(DriverZone(tenant_id=tid, driver_id=d.id, zone_id=zones[zone_name].id))
        drivers[zone_name] = d

    # two price-list versions: the active one and the one it replaced
    old_list = PriceList(tenant_id=tid, branch_id=rid, version=13, status="superseded",
                         source_filename="riyadh-prices-v13.xlsx",
                         activated_at=now - timedelta(days=9), superseded_at=now - timedelta(days=1))
    new_list = PriceList(tenant_id=tid, branch_id=rid, version=14, status="active",
                         source_filename="riyadh-prices-v14.xlsx", activated_at=now - timedelta(days=1))
    db.add_all([old_list, new_list])
    await db.flush()

    products = {}
    for sku, en, ar, price, cost, stock in PRODUCTS:
        p = Product(tenant_id=tid, sku=sku, name_en=en, name_ar=ar, category="Fresh produce",
                    cost_price=Decimal(cost) if cost else None, cost_currency=CURRENCY if cost else None)
        db.add(p)
        await db.flush()
        products[sku] = (p, Decimal(price), Decimal(cost) if cost else None)
        db.add(ProductPrice(tenant_id=tid, branch_id=rid, product_id=p.id, price_list_id=old_list.id,
                            unit_price=Decimal(price) - 1, currency=CURRENCY, sheet_quantity=stock + 40,
                            effective_from=now - timedelta(days=9), effective_to=now - timedelta(days=1)))
        db.add(ProductPrice(tenant_id=tid, branch_id=rid, product_id=p.id, price_list_id=new_list.id,
                            unit_price=Decimal(price), currency=CURRENCY, sheet_quantity=stock,
                            unit_cost=Decimal(cost) if cost else None,
                            effective_from=now - timedelta(days=1), effective_to=None))
        db.add(Inventory(tenant_id=tid, branch_id=rid, product_id=p.id, quantity_on_hand=stock))

    customers = []
    for i, (name, zone_name, gap) in enumerate(CUSTOMERS):
        c = Customer(tenant_id=tid, branch_id=rid, name=name, company=name, whatsapp_number=f"+96650000{i:04d}",
                     address=f"{zone_name}, Riyadh", zone_id=zones[zone_name].id)
        db.add(c)
        customers.append((c, zone_name, gap))
    await db.flush()

    # order history: each customer orders on their own rhythm over ~60 days
    planned = []
    for c, zone_name, gap in customers:
        last = QUIET.get(c.name, rng.uniform(0.2, gap))
        t = 60.0
        while t > last:
            planned.append((now - timedelta(days=t, hours=rng.uniform(0, 6)), c, zone_name))
            t -= gap * rng.uniform(0.8, 1.2)
    planned.sort(key=lambda x: x[0])

    skus = [s for s, *_ in PRODUCTS if s != "MAN-4"]
    for n, (created, c, zone_name) in enumerate(planned, start=1):
        age_h = (now - created).total_seconds() / 3600
        if age_h > 48:
            status = "completed"
        elif age_h > 30:
            status = "delivered"
        elif age_h > 14:
            status = "dispatched"
        elif age_h > 6:
            status = "preparing"
        else:
            status = "confirmed"
        if n % 17 == 0 and status == "completed":
            status = "cancelled"
        driver = drivers.get(zone_name)
        order = Order(tenant_id=tid, branch_id=rid, order_number=f"ORD-{n:05d}", customer_id=c.id, customer_name=c.name,
                      customer_company=c.company, whatsapp_number=c.whatsapp_number, status=status,
                      currency=CURRENCY, price_list_id=new_list.id, zone_id=c.zone_id,
                      assigned_driver_id=driver.id if driver and status in ("dispatched", "delivered", "completed") else None,
                      confirmed_at=created, cancelled_at=created + timedelta(hours=2) if status == "cancelled" else None,
                      created_at=created, total_amount=Decimal("0"))
        db.add(order)
        await db.flush()
        total = Decimal("0")
        for sku in rng.sample(skus, rng.randint(1, 3)):
            p, price, cost = products[sku]
            qty = rng.randint(5, 30)
            total += price * qty
            db.add(OrderItem(tenant_id=tid, order_id=order.id, product_id=p.id, sku=sku, product_name=p.name_en,
                             quantity=qty, unit_price=price, line_total=price * qty, unit_cost=cost,
                             created_at=created))
        order.total_amount = total
        # status history (drives "Stuck orders" and the order timeline)
        steps = ["confirmed"] if status == "cancelled" else FLOW[: FLOW.index(status) + 1]
        at, prev = created, None
        for st in steps:
            db.add(OrderEvent(tenant_id=tid, order_id=order.id, from_status=prev, to_status=st,
                              actor_name="Salesman AI" if st == "confirmed" else "Team", created_at=at))
            prev, at = st, at + timedelta(hours=rng.uniform(1, 5))
        if status == "cancelled":
            db.add(OrderEvent(tenant_id=tid, order_id=order.id, from_status="confirmed", to_status="cancelled",
                              actor_name="Team", note="Customer cancelled by phone", created_at=created + timedelta(hours=2)))

    # one delivery that has been out with the driver too long (shows under "Stuck orders")
    alnoor = next(c for c, *_ in customers if c.name == "Al Noor Grocery")
    tom, tom_price, tom_cost = products["TOM-5"]
    late_at = now - timedelta(hours=31)
    late = Order(tenant_id=tid, branch_id=rid, order_number=f"ORD-{len(planned) + 1:05d}", customer_id=alnoor.id,
                 customer_name=alnoor.name, customer_company=alnoor.company, whatsapp_number=alnoor.whatsapp_number,
                 status="dispatched", currency=CURRENCY, price_list_id=new_list.id, zone_id=alnoor.zone_id,
                 assigned_driver_id=drivers["Riyadh North"].id, confirmed_at=late_at - timedelta(hours=3),
                 created_at=late_at - timedelta(hours=3), total_amount=tom_price * 20)
    db.add(late)
    await db.flush()
    db.add(OrderItem(tenant_id=tid, order_id=late.id, product_id=tom.id, sku="TOM-5", product_name=tom.name_en,
                     quantity=20, unit_price=tom_price, line_total=tom_price * 20, unit_cost=tom_cost,
                     created_at=late_at - timedelta(hours=3)))
    for frm, to, at in ((None, "confirmed", late_at - timedelta(hours=3)), ("confirmed", "preparing", late_at - timedelta(hours=2)),
                        ("preparing", "dispatched", late_at)):
        db.add(OrderEvent(tenant_id=tid, order_id=late.id, from_status=frm, to_status=to,
                          actor_name="Salesman AI" if to == "confirmed" else "Team", created_at=at))

    # one order waiting for a human decision (short stock)
    hayat = next(c for c, *_ in customers if c.name == "Hayat Minimarket")
    mango, mango_price, _ = products["MAN-4"]
    held_num = f"ORD-{len(planned) + 2:05d}"
    held = Order(tenant_id=tid, branch_id=rid, order_number=held_num, customer_id=hayat.id, customer_name=hayat.name,
                 customer_company=hayat.company, whatsapp_number=hayat.whatsapp_number,
                 status="requires_human_review", currency=CURRENCY, zone_id=hayat.zone_id,
                 total_amount=mango_price * 50, created_at=now - timedelta(minutes=40))
    db.add(held)
    await db.flush()
    db.add(OrderItem(tenant_id=tid, order_id=held.id, product_id=mango.id, sku="MAN-4", product_name=mango.name_en,
                     quantity=50, unit_price=mango_price, line_total=mango_price * 50, available_at_order=32))
    db.add(Escalation(tenant_id=tid, branch_id=rid, reason_type="insufficient_stock",
                      context={"order_number": held_num,
                               "shortfalls": [{"sku": "MAN-4", "requested": 50, "available": 32}]},
                      ai_recommendation="Insufficient stock -> MAN-4: requested 50, only 32 available. "
                                        "Approve partial/backorder or reject.",
                      order_id=held.id, customer_name=hayat.name, whatsapp_number=hayat.whatsapp_number,
                      status="open"))

    # conversations, English and Arabic
    noor = next(c for c, *_ in customers if c.name == "Al Noor Grocery")
    waha = next(c for c, *_ in customers if c.name == "Al Waha Market")
    chats = [
        (noor, "en", [
            ("in", "Salam, what's the price of tomatoes today? Need 30 cartons"),
            ("out", "Wa alaikum salam 👋 Tomatoes (5 kg carton): SAR 35, today's price. 30 cartons are available. "
                    "30 × SAR 35 = SAR 1,050. Shall I place the order?"),
            ("in", "Yes, confirm"),
            ("out", "✅ Your order is confirmed. Thank you!"),
        ]),
        (waha, "ar", [
            ("in", "أبغى ٢٠ كرتون خيار و١٠ كراتين برتقال، كم المجموع؟"),
            ("out", "هلا 👋 حسب أسعار اليوم: خيار (٥ كجم) × ٢٠ = ٥٦٠ ر.س، برتقال (٨ كجم) × ١٠ = ٤٢٠ ر.س. "
                    "الإجمالي ٩٨٠ ر.س. هل أؤكد الطلب؟"),
            ("in", "أكد"),
            ("out", "✅ تم تأكيد طلبك. شكراً لك!"),
        ]),
        (hayat, "en", [
            ("in", "Send 50 boxes of mangoes for tomorrow morning"),
            ("out", "We have 32 boxes of mangoes (4 kg) in stock right now. I've sent your request for 50 "
                    "to our team — they'll confirm shortly."),
        ]),
    ]
    for c, lang, msgs in chats:
        start = now - timedelta(hours=rng.uniform(1, 20))
        conv = Conversation(tenant_id=tid, branch_id=rid, customer_number=c.whatsapp_number, customer_name=c.name,
                            language=lang, status="active", last_message_at=start + timedelta(minutes=len(msgs)))
        db.add(conv)
        await db.flush()
        for i, (direction, text) in enumerate(msgs):
            db.add(Message(tenant_id=tid, conversation_id=conv.id, direction=direction,
                           sender="customer" if direction == "in" else "ai", msg_type="text", content=text,
                           created_at=start + timedelta(minutes=i)))

    await db.commit()
    await _seed_jeddah(db, tid, jeddah.id, products, rng, now, first_number=len(planned) + 3)
    await _seed_prospects(db, tid, rep, zones, now)
    await _seed_accounts(db, tid, now)
    await _seed_einvoicing(db, tid, rid, now)
    return tenant


# Jeddah: its own prices (a little higher), stock, zones, driver and customers
JEDDAH_PRICES = {"TOM-5": ("37.00", 120), "POT-10": ("23.00", 90), "CUC-5": ("29.50", 60),
                 "ORA-8": ("44.00", 40), "MAN-4": ("50.00", 25), "ONI-10": ("19.00", 70)}
JEDDAH_ZONES = ["Jeddah Al Rawdah", "Jeddah Al Safa"]
JEDDAH_CUSTOMERS = [("Al Balad Grocery", "Jeddah Al Rawdah", 4), ("Corniche Fresh Mart", "Jeddah Al Safa", 5)]


async def _seed_jeddah(db: AsyncSession, tid, bid, products: dict, rng: random.Random, now: datetime,
                       first_number: int) -> None:
    plist = PriceList(tenant_id=tid, branch_id=bid, version=1, status="active",
                      source_filename="jeddah-prices-v1.xlsx", activated_at=now - timedelta(days=2))
    db.add(plist)
    await db.flush()
    prices = {}
    for sku, (price, stock) in JEDDAH_PRICES.items():
        p, _, cost = products[sku]
        prices[sku] = (p, Decimal(price), cost)
        db.add(ProductPrice(tenant_id=tid, branch_id=bid, product_id=p.id, price_list_id=plist.id,
                            unit_price=Decimal(price), currency=CURRENCY, sheet_quantity=stock,
                            effective_from=now - timedelta(days=2), effective_to=None))
        db.add(Inventory(tenant_id=tid, branch_id=bid, product_id=p.id, quantity_on_hand=stock))

    zones = {}
    for name in JEDDAH_ZONES:
        z = Zone(tenant_id=tid, branch_id=bid, name=name, description=f"{name} delivery area")
        db.add(z)
        zones[name] = z
    await db.flush()
    driver = User(tenant_id=tid, branch_id=bid, email=f"hamad.demo.{uuid.uuid4().hex[:6]}@example.com",
                  password_hash=hash_password(uuid.uuid4().hex), full_name="Hamad", role=UserRole.DRIVER.value)
    db.add(driver)
    await db.flush()
    for z in zones.values():
        db.add(DriverZone(tenant_id=tid, driver_id=driver.id, zone_id=z.id))

    n = first_number
    for i, (name, zone_name, gap) in enumerate(JEDDAH_CUSTOMERS):
        c = Customer(tenant_id=tid, branch_id=bid, name=name, company=name,
                     whatsapp_number=f"+96655000{i:04d}", address=f"{zone_name}, Jeddah",
                     zone_id=zones[zone_name].id)
        db.add(c)
        await db.flush()
        t = 30.0
        while t > 2:
            created = now - timedelta(days=t, hours=rng.uniform(0, 6))
            order = Order(tenant_id=tid, branch_id=bid, order_number=f"ORD-{n:05d}", customer_id=c.id,
                          customer_name=c.name, customer_company=c.company, whatsapp_number=c.whatsapp_number,
                          status="completed", currency=CURRENCY, price_list_id=plist.id, zone_id=c.zone_id,
                          assigned_driver_id=driver.id, confirmed_at=created, created_at=created,
                          total_amount=Decimal("0"))
            db.add(order)
            await db.flush()
            total = Decimal("0")
            for sku in rng.sample(["TOM-5", "POT-10", "CUC-5", "ONI-10"], 2):
                p, price, cost = prices[sku]
                qty = rng.randint(5, 25)
                total += price * qty
                db.add(OrderItem(tenant_id=tid, order_id=order.id, product_id=p.id, sku=sku,
                                 product_name=p.name_en, quantity=qty, unit_price=price,
                                 line_total=price * qty, unit_cost=cost, created_at=created))
            order.total_amount = total
            at, prev = created, None
            for st in FLOW:
                db.add(OrderEvent(tenant_id=tid, order_id=order.id, from_status=prev, to_status=st,
                                  actor_name="Salesman AI" if st == "confirmed" else "Team", created_at=at))
                prev, at = st, at + timedelta(hours=rng.uniform(1, 4))
            n += 1
            t -= gap * rng.uniform(0.8, 1.2)
    await db.commit()


# new shops in the pipeline: name, source, zone, phone, status, note
PROSPECTS = [
    ("Al Maather Grocery", "google", "Riyadh North", "+966500100201", "contacted", None),
    ("Qurtubah Fresh Market", "import", "Riyadh East", "+966500100202", "interested",
     "Wants a sample delivery on Thursday morning"),
    ("Hittin Mini Mart", "import", "Riyadh West", "+966500100203", "new", None),
    ("Al Yasmin Supermarket", "manual", None, "+966500100204", "new", None),
    ("Laban Corner Store", "import", "Riyadh Central", None, "new", None),
    ("Al Rawdah Baqala", "import", "Riyadh East", "+966500100206", "lost", None),
]


async def _seed_prospects(db: AsyncSession, tid, rep: User, zones: dict, now: datetime) -> None:
    from app.modules.prospects.service import refresh_winbacks

    for i, (name, source, zone_name, phone, status, note) in enumerate(PROSPECTS):
        p = Prospect(tenant_id=tid, branch_id=zones[zone_name].branch_id if zone_name else None,
                     kind="new", source=source, status=status, name=name, phone=phone,
                     zone_id=zones[zone_name].id if zone_name else None,
                     area="Al Yasmin" if zone_name is None else None, category="Grocery",
                     assigned_to_id=rep.id, created_by_id=rep.id,
                     google_place_id=f"demo-place-{i}" if source == "google" else None,
                     lost_reason="Has a fixed supplier contract" if status == "lost" else None,
                     created_at=now - timedelta(days=6 - i))
        if status in ("contacted", "interested"):
            p.last_contacted_at = now - timedelta(days=2)
        if status == "lost":
            p.closed_at = now - timedelta(days=1)
        db.add(p)
        await db.flush()
        origin = {"google": "Added from Google Maps", "import": "Imported (row %d)" % (i + 2),
                  "manual": "Added by hand"}[source]
        db.add(ProspectActivity(tenant_id=tid, prospect_id=p.id, kind="created", body=origin,
                                actor_id=rep.id, actor_name=rep.full_name, created_at=p.created_at))
        if p.last_contacted_at:
            db.add(ProspectActivity(
                tenant_id=tid, prospect_id=p.id, kind="contacted", actor_id=rep.id, actor_name=rep.full_name,
                body=f"Hello {name}, this is Nasser from {DEMO_NAME.split(' — ')[-1]}. We supply shops at wholesale "
                     "prices. Some of today's prices: Tomatoes 5 kg: SAR 35; Potatoes 10 kg: SAR 22. "
                     "Would you like our full price list on WhatsApp?",
                created_at=p.last_contacted_at))
        if note:
            db.add(ProspectActivity(tenant_id=tid, prospect_id=p.id, kind="note", body=note,
                                    actor_id=rep.id, actor_name=rep.full_name, created_at=now - timedelta(days=1)))
    await db.commit()
    # quiet customers become win-back prospects, exactly as the "Find quiet customers" button does
    await refresh_winbacks(db, tid, rep)


# credit limit per customer (None = no limit); the last two are left with overdue invoices
CREDIT = {
    "Al Noor Grocery": Decimal("15000"), "Al Waha Market": Decimal("8000"), "Hayat Minimarket": Decimal("15000"),
    "Green Valley Store": Decimal("8000"), "Al Safa Supermarket": Decimal("9000"), "Riyadh Fresh Mart": None,
    "Bait Al Khair": Decimal("12000"),
}
LATE_PAYERS = {"Al Waha Market", "Al Safa Supermarket"}
B2B_CUSTOMERS = {
    "Al Noor Grocery": dict(vat_number="310000000000003", street="King Abdulaziz Rd", building_number="2611",
                            district="Al Sahafah", city="Riyadh", postal_code="13321"),
    "Riyadh Fresh Mart": dict(cr_number="1010456789", street="Olaya St", building_number="3150",
                              district="Al Olaya", city="Riyadh", postal_code="12214"),
}


async def _seed_accounts(db: AsyncSession, tid, now: datetime) -> None:
    """Invoices for recent deliveries, payments for most of them, and two customers running late."""
    from app.modules.accounts import service as accounts

    await accounts.update_settings(db, tid, {
        "seller_name": "Fresh Produce Wholesale Co.", "seller_name_ar": "شركة الخضار والفواكه بالجملة",
        "seller_vat_number": "300000000000003", "seller_cr_number": "1010000000",
        "seller_address": "Al Aziziyah wholesale market, Riyadh 14513", "default_payment_terms_days": 30,
        "seller_street": "Al Aziziyah wholesale market", "seller_building_number": "7421",
        "seller_district": "Al Aziziyah", "seller_city": "Riyadh", "seller_postal_code": "14513",
        "invoice_footer": "Bank transfer: Demo Bank | IBAN SA00 0000 0000 0000 0000 0000 | Use the invoice number as reference.",
    })
    customers = {c.name: c for c in await db.scalars(select(Customer).where(Customer.tenant_id == tid))}
    for name, limit in CREDIT.items():
        if name in customers:
            customers[name].credit_limit = limit
    # two business customers with tax registrations get standard (B2B) e-invoices
    for name, extra in B2B_CUSTOMERS.items():
        if name in customers:
            for key, value in extra.items():
                setattr(customers[name], key, value)
    await db.commit()

    today = now.date()
    delivered = list(await db.scalars(
        select(Order).where(
            Order.tenant_id == tid, Order.customer_id.is_not(None), Order.status.in_(("delivered", "completed")),
            Order.created_at >= now - timedelta(days=55),
        ).order_by(Order.created_at)
    ))
    for order in delivered:
        inv = await accounts.issue_invoice_for_order(db, order)
        # date the invoice the day after the order, as if it was issued on delivery
        issued = (order.created_at + timedelta(days=1)).date()
        inv.issue_date, inv.due_date = issued, issued + timedelta(days=30)
        inv.issued_at = order.created_at + timedelta(days=1)
        await db.execute(update(AccountEntry).where(AccountEntry.invoice_id == inv.id).values(entry_date=issued))
        await db.commit()

    # customers pay what fell due, a few days early; late payers have paid nothing for six weeks
    for name, c in customers.items():
        due = list(await db.scalars(
            select(SalesInvoice).where(SalesInvoice.customer_id == c.id, SalesInvoice.due_date <= today + timedelta(days=3))
            .order_by(SalesInvoice.due_date)
        ))
        if not due:
            continue
        if name in LATE_PAYERS:
            due = [i for i in due if i.issue_date < today - timedelta(days=85)]
        amount = sum((i.total for i in due), Decimal("0"))
        if amount > 0:
            await accounts.record_payment(
                db, tid, customer_id=c.id, invoice_id=None, amount=amount, method="bank_transfer",
                reference=f"TRX-{sum(map(ord, name)) * 37 % 90000 + 10000}", paid_on=min(today, max(i.due_date for i in due) - timedelta(days=2)),
                notes=None, actor_id=None,
            )


async def _seed_einvoicing(db: AsyncSession, tid, branch_id, now: datetime) -> None:
    """The Riyadh branch connected to ZATCA (with a demo certificate) and its e-invoices.

    Every invoice and credit note is signed for real -- hash chain, QR code and
    all -- but nothing is sent: the demo marks them cleared or reported, keeps
    two waiting and one rejected, so every state can be seen.
    """
    from app.modules.zatca import crypto
    from app.modules.zatca import service as zatca
    from app.modules.zatca import xml as zx
    from app.core.secret_box import seal

    key = crypto.new_private_key_pem()
    cert = crypto.demo_certificate(key, "Salesman-Riyadh")
    unit = ZatcaUnit(
        tenant_id=tid, branch_id=branch_id, environment="sandbox", status="active", common_name="Salesman-Riyadh",
        egs_serial=f"1-Salesman|2-2.0|3-{uuid.uuid4()}", organization_unit="Riyadh", invoice_types="1100",
        location="Al Aziziyah, Riyadh", industry="Wholesale of fruit and vegetables", private_key=seal(key),
        csr="demo", compliance_results=[{"label": label, "status": "PASS", "errors": [], "warnings": []} for label in (
            "Standard invoice", "Standard credit note", "Standard debit note",
            "Simplified invoice", "Simplified credit note", "Simplified debit note")],
        production_token="demo", production_secret=seal("demo"), certificate=cert,
        certificate_expires_at=now + timedelta(days=365 * 3), icv=0, last_hash=zx.FIRST_PIH,
        onboarded_at=now - timedelta(days=60),
    )
    db.add(unit)
    await db.flush()
    invoices = list(await db.scalars(
        select(SalesInvoice).where(SalesInvoice.tenant_id == tid, SalesInvoice.branch_id == branch_id,
                                   SalesInvoice.kind.in_(("invoice", "credit_note")))
        .order_by(SalesInvoice.issued_at, SalesInvoice.number)
    ))
    docs = []
    for inv in invoices:
        doc = await zatca.stamp(db, inv)
        if doc is not None:
            doc.signed_at = doc.submitted_at = inv.issued_at
            docs.append(doc)
    for doc in docs:
        if doc.status == "queued":
            doc.status = "cleared" if doc.flow == "standard" else "reported"
            doc.zatca_status = doc.status.upper()
            doc.attempts = 1
            if doc.flow == "standard":
                doc.cleared_xml = doc.xml
    # the two newest are still on their way; one older B2B invoice was rejected
    for doc in docs[-2:]:
        doc.status, doc.zatca_status, doc.attempts, doc.submitted_at = "queued", None, 0, None
    rejected = next((d for d in reversed(docs[:-2]) if d.flow == "standard" and d.kind == "invoice"), None)
    if rejected is not None:
        rejected.status, rejected.zatca_status, rejected.cleared_xml = "rejected", "NOT_CLEARED", None
        rejected.errors = [{"code": "BR-KSA-63", "category": "KSA",
                            "message": "If the buyer country code is SA, the buyer's street, building number, "
                                       "postal code, city and district are mandatory."}]
    # demo documents are never sent anywhere
    await db.execute(delete(Job).where(Job.tenant_id == tid, Job.kind == "zatca.submit"))
    await db.commit()


async def _main(email: str, password: str, reset: bool) -> None:
    from app.db.session import SessionLocal, engine

    async with SessionLocal() as db:
        tenant = await seed(db, email, password, reset=reset)
    await engine.dispose()
    print(f"Demo ready: tenant '{tenant.name}'. Sign in as {email} (read-only).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", required=True, help="login email for the demo account")
    ap.add_argument("--password", required=True, help="password for the demo account (12+ characters)")
    ap.add_argument("--reset", action="store_true", help="delete and rebuild the demo tenant")
    a = ap.parse_args()
    if len(a.password) < 12:
        raise SystemExit("Use a password of at least 12 characters; this account is shared with prospects.")
    asyncio.run(_main(a.email.strip().lower(), a.password, a.reset))


if __name__ == "__main__":
    main()