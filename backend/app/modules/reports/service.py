"""Daily sales reporting.

Reports are computed on demand from the immutable order/inventory data (which
is already the stored source of truth), so nothing extra needs persisting and
it works on ephemeral-disk hosts. The same compute function will later be
called by a scheduled worker to auto-generate end-of-day reports.
"""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fpdf import FPDF
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.inventory import Inventory
from app.db.models.order import Order
from app.db.models.order_item import OrderItem
from app.db.models.product import Product

_CONFIRMED = ("confirmed", "completed")


def _sanitize(text: str) -> str:
    """fpdf core fonts are latin-1; replace unsupported chars so we never crash.
    (Full Unicode/Arabic PDF support = embed a TTF font later.)"""
    return (text or "").encode("latin-1", "replace").decode("latin-1")


async def compute_daily_summary(
    db: AsyncSession, tenant_id: uuid.UUID, day: date, scope: uuid.UUID | None = None
) -> dict:
    """One day's sales for one branch, or for all branches when scope is None."""
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    q = select(Order).where(
        Order.tenant_id == tenant_id,
        Order.created_at >= start,
        Order.created_at < end,
    )
    if scope is not None:
        q = q.where(Order.branch_id == scope)
    orders = list(await db.scalars(q.order_by(Order.created_at)))

    total_orders = len(orders)
    confirmed = [o for o in orders if o.status in _CONFIRMED]
    cancelled = [o for o in orders if o.status == "cancelled"]
    review = [o for o in orders if o.status == "requires_human_review"]

    total_revenue = sum((Decimal(str(o.total_amount)) for o in confirmed), Decimal("0"))
    avg_order = (total_revenue / len(confirmed)) if confirmed else Decimal("0")

    # products sold that day (from confirmed orders)
    confirmed_ids = [o.id for o in confirmed]
    product_rows: dict[str, dict] = {}
    if confirmed_ids:
        items = list(
            await db.scalars(
                select(OrderItem).where(OrderItem.order_id.in_(confirmed_ids))
            )
        )
        for it in items:
            row = product_rows.setdefault(
                it.sku, {"sku": it.sku, "name": it.product_name, "qty": 0, "revenue": Decimal("0")}
            )
            row["qty"] += it.quantity
            row["revenue"] += Decimal(str(it.line_total))

    products_sold = sorted(product_rows.values(), key=lambda r: r["revenue"], reverse=True)

    # current remaining stock snapshot (summed across branches when looking at all)
    stock_q = (
        select(Product.sku, Product.name_en, func.sum(Inventory.quantity_on_hand))
        .join(Inventory, Inventory.product_id == Product.id)
        .where(Product.tenant_id == tenant_id)
        .group_by(Product.sku, Product.name_en)
        .order_by(Product.sku)
    )
    if scope is not None:
        stock_q = stock_q.where(Inventory.branch_id == scope)
    stock_rows = list(await db.execute(stock_q))
    remaining_stock = [
        {"sku": sku, "name": name, "quantity": int(qty or 0)} for sku, name, qty in stock_rows
    ]

    currency = confirmed[0].currency if confirmed else (orders[0].currency if orders else "USD")

    return {
        "date": day.isoformat(),
        "currency": currency,
        "totals": {
            "total_orders": total_orders,
            "confirmed_orders": len(confirmed),
            "cancelled_orders": len(cancelled),
            "review_orders": len(review),
            "total_revenue": float(total_revenue),
            "avg_order_value": float(avg_order),
            "total_units_sold": sum(r["qty"] for r in products_sold),
        },
        "products_sold": [
            {"sku": r["sku"], "name": r["name"], "qty": r["qty"], "revenue": float(r["revenue"])}
            for r in products_sold
        ],
        "remaining_stock": remaining_stock,
        "orders": [
            {
                "order_number": o.order_number,
                "customer": o.customer_name or "-",
                "status": o.status,
                "total": float(o.total_amount),
                "time": o.created_at.strftime("%H:%M"),
            }
            for o in orders
        ],
    }


def render_pdf(business_name: str, summary: dict) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    cur = summary["currency"]

    # header
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, _sanitize(business_name), ln=True)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(100)
    pdf.cell(0, 8, f"Daily Sales Report  -  {summary['date']}", ln=True)
    pdf.set_text_color(0)
    pdf.ln(4)

    # summary grid
    t = summary["totals"]
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Summary", ln=True)
    pdf.set_font("Helvetica", "", 11)
    rows = [
        ("Total orders", str(t["total_orders"])),
        ("Confirmed", str(t["confirmed_orders"])),
        ("Cancelled", str(t["cancelled_orders"])),
        ("Needs review", str(t["review_orders"])),
        (f"Revenue ({cur})", f"{t['total_revenue']:,.2f}"),
        (f"Avg order ({cur})", f"{t['avg_order_value']:,.2f}"),
        ("Units sold", str(t["total_units_sold"])),
    ]
    for label, value in rows:
        pdf.cell(60, 7, label, border=0)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, value, ln=True)
        pdf.set_font("Helvetica", "", 11)
    pdf.ln(4)

    # products sold table
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Products Sold", ln=True)
    if summary["products_sold"]:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(240)
        pdf.cell(30, 7, "SKU", border=1, fill=True)
        pdf.cell(85, 7, "Product", border=1, fill=True)
        pdf.cell(25, 7, "Qty", border=1, fill=True, align="R")
        pdf.cell(0, 7, f"Revenue ({cur})", border=1, fill=True, align="R", ln=True)
        pdf.set_font("Helvetica", "", 10)
        for r in summary["products_sold"]:
            pdf.cell(30, 7, _sanitize(r["sku"]), border=1)
            pdf.cell(85, 7, _sanitize(r["name"])[:45], border=1)
            pdf.cell(25, 7, str(r["qty"]), border=1, align="R")
            pdf.cell(0, 7, f"{r['revenue']:,.2f}", border=1, align="R", ln=True)
    else:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 7, "No products sold on this day.", ln=True)
    pdf.ln(4)

    # orders table
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Orders", ln=True)
    if summary["orders"]:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(240)
        pdf.cell(30, 7, "Order", border=1, fill=True)
        pdf.cell(50, 7, "Customer", border=1, fill=True)
        pdf.cell(45, 7, "Status", border=1, fill=True)
        pdf.cell(20, 7, "Time", border=1, fill=True)
        pdf.cell(0, 7, f"Total ({cur})", border=1, fill=True, align="R", ln=True)
        pdf.set_font("Helvetica", "", 10)
        for o in summary["orders"]:
            pdf.cell(30, 7, _sanitize(o["order_number"]), border=1)
            pdf.cell(50, 7, _sanitize(o["customer"])[:26], border=1)
            pdf.cell(45, 7, _sanitize(o["status"].replace("_", " ")), border=1)
            pdf.cell(20, 7, o["time"], border=1)
            pdf.cell(0, 7, f"{o['total']:,.2f}", border=1, align="R", ln=True)
    else:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 7, "No orders on this day.", ln=True)

    out = pdf.output()
    return bytes(out)