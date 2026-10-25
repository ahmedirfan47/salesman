"""AI-drafted first-contact and win-back WhatsApp messages.

The rule from the ordering agent holds here too: the model never states a
price it wasn't given. It gets a short fact sheet built from the database
(today's prices, the shop's usual products), and every number in its draft
is checked against that sheet. A draft that mentions any other number, a
link, or is in the wrong language is discarded and a fixed template is used
instead, so the rep always gets a message that is safe to send.
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import chat
from app.db.models.inventory import Inventory
from app.db.models.order import Order
from app.db.models.order_item import OrderItem
from app.db.models.product import Product
from app.db.models.product_price import ProductPrice
from app.db.models.prospect import Prospect
from app.db.models.zone import Zone
from app.modules.analytics.service import REVENUE_STATUSES

logger = logging.getLogger("salesman.prospects")

_MAX_PRODUCTS = 3
_LLM_TIMEOUT_SECONDS = 20
_CCY_AR = {"SAR": "ر.س", "AED": "د.إ", "PKR": "روبية", "USD": "دولار"}
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫٬", "01234567890123456789.,")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_ARABIC = re.compile(r"[\u0600-\u06FF]")


@dataclass
class PricedProduct:
    name_en: str
    name_ar: str | None
    price: Decimal
    currency: str

    def label(self, language: str) -> str:
        name = self.name_ar if language == "ar" and self.name_ar else self.name_en
        ccy = _CCY_AR.get(self.currency, self.currency) if language == "ar" else self.currency
        amount = _fmt(self.price)
        return f"{name}: {amount} {ccy}" if language == "ar" else f"{name}: {ccy} {amount}"


@dataclass
class Facts:
    language: str
    business: str
    rep: str | None
    shop: str
    contact: str | None
    area: str | None
    winback: bool
    insight: str | None
    products: list[PricedProduct] = field(default_factory=list)

    def sheet(self) -> str:
        lines = [
            f"Company: {self.business}",
            f"Sales rep: {self.rep or '(no name; sign as the sales team)'}",
            f"Shop: {self.shop}",
        ]
        if self.contact:
            lines.append(f"Contact person: {self.contact}")
        if self.area:
            lines.append(f"Area: {self.area}")
        if self.winback and self.insight:
            lines.append(f"History: {self.insight}")
        if self.products:
            lines.append("Prices today (use only these, exactly as written):")
            lines += [f"- {p.label(self.language)}" for p in self.products]
        else:
            lines.append("Prices today: none available -- do not mention any price.")
        return "\n".join(lines)


def _fmt(price: Decimal) -> str:
    return str(price.quantize(Decimal("1"))) if price == price.to_integral_value() else f"{price:.2f}"


def _canon(number: str) -> str | None:
    try:
        return format(Decimal(number.replace(",", "")).normalize(), "f")
    except InvalidOperation:
        return None


def _numbers(text: str) -> set[str]:
    return {c for c in (_canon(n) for n in _NUMBER.findall(text.translate(_DIGITS))) if c is not None}


# --- facts from the database ------------------------------------------------

async def _priced_in_stock(db: AsyncSession, tenant_id) -> dict:
    rows = await db.execute(
        select(Product, ProductPrice.unit_price, ProductPrice.currency, Inventory.quantity_on_hand)
        .join(ProductPrice, (ProductPrice.product_id == Product.id) & ProductPrice.effective_to.is_(None))
        .outerjoin(Inventory, Inventory.product_id == Product.id)
        .where(Product.tenant_id == tenant_id, Product.is_active.is_(True))
    )
    out = {}
    for product, price, currency, qty in rows:
        if (qty or 0) > 0:
            out[product.id] = PricedProduct(product.name_en, product.name_ar, Decimal(str(price)), currency)
    return out


async def _sold_quantities(db: AsyncSession, tenant_id, *, customer_id=None, days: int | None = None) -> list:
    q = (
        select(OrderItem.product_id, func.sum(OrderItem.quantity).label("qty"))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.tenant_id == tenant_id, Order.status.in_(REVENUE_STATUSES))
        .group_by(OrderItem.product_id)
        .order_by(func.sum(OrderItem.quantity).desc())
    )
    if customer_id is not None:
        q = q.where(Order.customer_id == customer_id)
    if days is not None:
        q = q.where(Order.created_at >= datetime.now(timezone.utc) - timedelta(days=days))
    return [r.product_id for r in await db.execute(q)]


async def build_facts(db: AsyncSession, prospect: Prospect, *, business: str, rep: str | None, language: str) -> Facts:
    priced = await _priced_in_stock(db, prospect.tenant_id)
    chosen: list[PricedProduct] = []

    if prospect.kind == "winback" and prospect.customer_id:
        for pid in await _sold_quantities(db, prospect.tenant_id, customer_id=prospect.customer_id):
            if pid in priced:
                chosen.append(priced[pid])
            if len(chosen) == _MAX_PRODUCTS:
                break
    if not chosen:
        ranked = await _sold_quantities(db, prospect.tenant_id, days=60)
        for pid in ranked + [pid for pid in priced if pid not in ranked]:
            if pid in priced:
                chosen.append(priced[pid])
            if len(chosen) == _MAX_PRODUCTS:
                break

    area = prospect.area
    if not area and prospect.zone_id:
        area = await db.scalar(select(Zone.name).where(Zone.id == prospect.zone_id))

    return Facts(
        language=language, business=business, rep=rep, shop=prospect.name, contact=prospect.contact_name,
        area=area, winback=prospect.kind == "winback", insight=prospect.insight, products=chosen,
    )


# --- templates (always safe) ---------------------------------------------------

def template_message(f: Facts) -> str:
    greet_name = f.contact or f.shop
    if f.language == "ar":
        who = f"معك {f.rep} من {f.business}" if f.rep else f"معك فريق المبيعات في {f.business}"
        prices = "، ".join(p.label("ar") for p in f.products)
        if f.winback:
            parts = [f"السلام عليكم {greet_name}، {who}.", "افتقدنا طلباتك مؤخراً وحبينا نطمّن عليك."]
            if prices:
                parts.append(f"أسعار أصنافك المعتادة اليوم: {prices}.")
            parts.append("هل نجهّز لك طلب؟")
        else:
            where = f" في {f.area}" if f.area else ""
            parts = [f"السلام عليكم {greet_name}، {who}.", f"نورّد للمحلات{where} بأسعار الجملة."]
            if prices:
                parts.append(f"من أسعار اليوم: {prices}.")
            parts.append("هل ترغب أن نرسل لك قائمة الأسعار كاملة؟")
        return " ".join(parts)

    who = f"this is {f.rep} from {f.business}" if f.rep else f"this is the sales team at {f.business}"
    prices = "; ".join(p.label("en") for p in f.products)
    if f.winback:
        parts = [f"Hello {greet_name}, {who}.", "We haven't had an order from you in a while and wanted to check everything is fine."]
        if prices:
            parts.append(f"Today's prices for your usual items: {prices}.")
        parts.append("Shall I put an order together for you?")
    else:
        where = f" in {f.area}" if f.area else ""
        parts = [f"Hello {greet_name}, {who}.", f"We supply shops{where} at wholesale prices."]
        if prices:
            parts.append(f"Some of today's prices: {prices}.")
        parts.append("Would you like our full price list on WhatsApp?")
    return " ".join(parts)


# --- AI draft -------------------------------------------------------------------

_SYSTEM = """You write short WhatsApp messages for a wholesale sales rep.

Rules:
- Write in {language}. {register}
- 2 to 5 short sentences, under 500 characters in total.
- Introduce the rep and the company from the fact sheet.
- Mention at most 3 products from the fact sheet, with their prices exactly as written there.
- Never mention any other price, discount, offer, delivery time, or any number that is not in the fact sheet.
- No links, no hashtags, no markdown, at most one emoji.
- End with one simple question.
- {purpose}
- Output only the message text."""

_PURPOSE_NEW = "This shop is not a customer yet. Introduce the company and invite them to see the price list."
_PURPOSE_WINBACK = ("This shop is an existing customer who has not ordered for longer than usual. Be warm, "
                    "do not guilt them, check that all is well, and mention items they usually buy.")


def check_draft(text: str, f: Facts) -> bool:
    """True if the draft is safe to show: right language, no links, no invented numbers."""
    if not text or len(text) > 1000:
        return False
    lowered = text.lower()
    if "http" in lowered or "www." in lowered:
        return False
    has_arabic = bool(_ARABIC.search(text))
    if f.language == "ar" and not has_arabic:
        return False
    if f.language == "en" and has_arabic:
        return False
    return _numbers(text) <= _numbers(f.sheet())


async def draft_message(f: Facts) -> tuple[str, str]:
    """Returns (message, source) where source is 'ai' or 'template'."""
    language = "Arabic" if f.language == "ar" else "English"
    register = ("Use polite Gulf Arabic suitable for a business message." if f.language == "ar"
                else "Use plain, friendly, professional English.")
    system = _SYSTEM.format(language=language, register=register,
                            purpose=_PURPOSE_WINBACK if f.winback else _PURPOSE_NEW)
    try:
        reply = await asyncio.wait_for(
            chat([{"role": "system", "content": system}, {"role": "user", "content": f.sheet()}]),
            timeout=_LLM_TIMEOUT_SECONDS,
        )
        text = (reply.content or "").strip().strip('"').strip()
    except Exception:  # noqa: BLE001 -- the rep still gets a usable message
        logger.warning("prospect draft: LLM unavailable, using template", exc_info=True)
        return template_message(f), "template"

    if check_draft(text, f):
        return text, "ai"
    logger.info("prospect draft rejected by safety check, using template")
    return template_message(f), "template"