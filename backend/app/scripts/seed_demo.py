"""Create (or reset) a read-only demo account with realistic sample data.

    python -m app.scripts.seed_demo --email demo@yourdomain.com --password 'a-strong-password'
    python -m app.scripts.seed_demo --email demo@yourdomain.com --password '...' --reset

The demo user has the 'demo' role: it can open every screen (orders,
analytics, conversations, zones, team...) but the API rejects every change.
All data lives in its own tenant, so it never touches a real customer's data.
--reset deletes that demo tenant and rebuilds it with fresh dates.
"""
import argparse
import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserRole
from app.core.security import hash_password
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
from app.db.models.tenant import Tenant
from app.db.models.user import User
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
    # children first (some FKs are RESTRICT), then the tenant
    for model in (Job, Message, Conversation, Escalation, PrintJob, OrderEvent, OrderItem, Order,
                  DriverZone, Customer, InventoryTransaction, Inventory, ProductPrice, PriceList,
                  Product, Zone):
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

    db.add(User(tenant_id=tid, email=email, password_hash=hash_password(password),
                full_name="Demo viewer", role=UserRole.DEMO.value))

    zones = {}
    for name in ZONES:
        z = Zone(tenant_id=tid, name=name, description=f"{name} delivery area")
        db.add(z)
        zones[name] = z
    await db.flush()

    drivers = {}
    for name, zone_name in DRIVERS:
        d = User(tenant_id=tid, email=f"{name.lower()}.demo.{uuid.uuid4().hex[:6]}@example.com",
                 password_hash=hash_password(uuid.uuid4().hex), full_name=name, role=UserRole.DRIVER.value)
        db.add(d)
        await db.flush()
        db.add(DriverZone(tenant_id=tid, driver_id=d.id, zone_id=zones[zone_name].id))
        drivers[zone_name] = d

    # two price-list versions: the active one and the one it replaced
    old_list = PriceList(tenant_id=tid, version=13, status="superseded", source_filename="prices-v13.xlsx",
                         activated_at=now - timedelta(days=9), superseded_at=now - timedelta(days=1))
    new_list = PriceList(tenant_id=tid, version=14, status="active", source_filename="prices-v14.xlsx",
                         activated_at=now - timedelta(days=1))
    db.add_all([old_list, new_list])
    await db.flush()

    products = {}
    for sku, en, ar, price, cost, stock in PRODUCTS:
        p = Product(tenant_id=tid, sku=sku, name_en=en, name_ar=ar, category="Fresh produce",
                    cost_price=Decimal(cost) if cost else None, cost_currency=CURRENCY if cost else None)
        db.add(p)
        await db.flush()
        products[sku] = (p, Decimal(price), Decimal(cost) if cost else None)
        db.add(ProductPrice(tenant_id=tid, product_id=p.id, price_list_id=old_list.id,
                            unit_price=Decimal(price) - 1, currency=CURRENCY, sheet_quantity=stock + 40,
                            effective_from=now - timedelta(days=9), effective_to=now - timedelta(days=1)))
        db.add(ProductPrice(tenant_id=tid, product_id=p.id, price_list_id=new_list.id,
                            unit_price=Decimal(price), currency=CURRENCY, sheet_quantity=stock,
                            unit_cost=Decimal(cost) if cost else None,
                            effective_from=now - timedelta(days=1), effective_to=None))
        db.add(Inventory(tenant_id=tid, product_id=p.id, quantity_on_hand=stock))

    customers = []
    for i, (name, zone_name, gap) in enumerate(CUSTOMERS):
        c = Customer(tenant_id=tid, name=name, company=name, whatsapp_number=f"+96650000{i:04d}",
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
        order = Order(tenant_id=tid, order_number=f"ORD-{n:05d}", customer_id=c.id, customer_name=c.name,
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
    late = Order(tenant_id=tid, order_number=f"ORD-{len(planned) + 1:05d}", customer_id=alnoor.id,
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
    held = Order(tenant_id=tid, order_number=held_num, customer_id=hayat.id, customer_name=hayat.name,
                 customer_company=hayat.company, whatsapp_number=hayat.whatsapp_number,
                 status="requires_human_review", currency=CURRENCY, zone_id=hayat.zone_id,
                 total_amount=mango_price * 50, created_at=now - timedelta(minutes=40))
    db.add(held)
    await db.flush()
    db.add(OrderItem(tenant_id=tid, order_id=held.id, product_id=mango.id, sku="MAN-4", product_name=mango.name_en,
                     quantity=50, unit_price=mango_price, line_total=mango_price * 50, available_at_order=32))
    db.add(Escalation(tenant_id=tid, reason_type="insufficient_stock",
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
        conv = Conversation(tenant_id=tid, customer_number=c.whatsapp_number, customer_name=c.name,
                            language=lang, status="active", last_message_at=start + timedelta(minutes=len(msgs)))
        db.add(conv)
        await db.flush()
        for i, (direction, text) in enumerate(msgs):
            db.add(Message(tenant_id=tid, conversation_id=conv.id, direction=direction,
                           sender="customer" if direction == "in" else "ai", msg_type="text", content=text,
                           created_at=start + timedelta(minutes=i)))

    await db.commit()
    return tenant


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