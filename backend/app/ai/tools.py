"""Agent tools. Each tool wraps a real service call against the tenant's data,
so the model can look up TRUE prices/stock and place orders -- never guess.

Tools run in the context of one branch (the branch whose WhatsApp number the
customer wrote to) and, when known, the customer's own number.

Account tools (balance, statement, invoice copies) only ever read the account
of the customer on file for the number that is writing -- never anyone else's.
"""
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.customer import Customer
from app.db.models.escalation import Escalation
from app.db.models.product import Product
from app.db.models.tenant import Tenant
from app.jobs.queue import WHATSAPP_SEND_DOCUMENT, enqueue
from app.modules.accounts import service as accounts
from app.modules.orders import service as orders_service
from app.modules.pricing import service as pricing_service
from app.schemas.order import OrderCreate, OrderItemIn

# ---- JSON schemas advertised to the model ----
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search the catalog by name or keyword to find a product's SKU. "
                           "Use this when the customer names a product but not its code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "product name or keyword"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_price_and_stock",
            "description": "Get the CURRENT price and available stock for a product SKU. "
                           "Always call this before quoting any price or availability. "
                           "Never state a price or stock number that did not come from this tool.",
            "parameters": {
                "type": "object",
                "properties": {"sku": {"type": "string"}},
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_order",
            "description": "Place a confirmed order for one or more products. Only call this "
                           "after the customer has confirmed the items and quantities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sku": {"type": "string"},
                                "quantity": {"type": "integer"},
                            },
                            "required": ["sku", "quantity"],
                        },
                    },
                    "customer_name": {"type": "string"},
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_account",
            "description": "Get the customer's own account: balance owed, credit limit, available credit, "
                           "overdue amount and unpaid invoices. Use this for any question about their balance, "
                           "what they owe, due dates or credit. Never state account figures that did not come "
                           "from this tool.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_my_statement",
            "description": "Send the customer their statement of account as a PDF on WhatsApp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "months": {"type": "integer", "description": "how many months back to cover (1-12, default 3)"},
                    "language": {"type": "string", "enum": ["en", "ar"], "description": "language of the conversation"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_invoice_copy",
            "description": "Send the customer a PDF copy of one of their own invoices or credit notes on WhatsApp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_number": {"type": "string", "description": "e.g. INV-000123"},
                    "language": {"type": "string", "enum": ["en", "ar"]},
                },
                "required": ["invoice_number"],
            },
        },
    },
]


@dataclass
class ToolContext:
    tenant_id: uuid.UUID
    branch_id: uuid.UUID
    customer_number: str | None = None


# ---- implementations ----
async def _search_products(db: AsyncSession, tenant_id: uuid.UUID, query: str) -> dict:
    like = f"%{query.strip()}%"
    rows = await db.scalars(
        select(Product)
        .where(
            Product.tenant_id == tenant_id,
            Product.is_active.is_(True),
            (Product.name_en.ilike(like))
            | (Product.name_ar.ilike(like))
            | (Product.sku.ilike(like)),
        )
        .limit(10)
    )
    products = [{"sku": p.sku, "name_en": p.name_en, "name_ar": p.name_ar} for p in rows]
    if not products:
        return {"found": False, "message": f"No products match '{query}'."}
    return {"found": True, "products": products}


async def _get_price_and_stock(db: AsyncSession, ctx: ToolContext, sku: str) -> dict:
    result = await pricing_service.get_current_price(db, ctx.tenant_id, sku, ctx.branch_id)
    if not result:
        return {"available": False, "message": f"No active price found for SKU '{sku}'."}
    return {
        "available": True,
        "sku": result["sku"],
        "name": result["name_en"],
        "unit_price": float(result["unit_price"]),
        "currency": result["currency"],
        "quantity_on_hand": result["quantity_on_hand"],
    }


async def _known_customer(db: AsyncSession, ctx: ToolContext) -> Customer | None:
    digits = re.sub(r"\D", "", ctx.customer_number or "")
    if not digits:
        return None
    return await db.scalar(
        select(Customer).where(
            Customer.tenant_id == ctx.tenant_id,
            func.regexp_replace(Customer.whatsapp_number, "[^0-9]", "", "g") == digits,
        )
    )


async def _place_order(
    db: AsyncSession, ctx: ToolContext, items: list[dict], customer_name: str | None = None
) -> dict:
    # Link the order to the customer on file (zone, delivery driver, order updates)
    # and to the branch the customer contacted.
    customer = await _known_customer(db, ctx)
    order = await orders_service.create_order(
        db,
        ctx.tenant_id,
        OrderCreate(
            items=[OrderItemIn(sku=i["sku"], quantity=int(i["quantity"])) for i in items],
            customer_id=customer.id if customer else None,
            customer_name=customer_name or (customer.name if customer else None),
            whatsapp_number=ctx.customer_number,
            branch_id=ctx.branch_id,
        ),
    )
    review_reason = None
    if order.status == "requires_human_review":
        reason = await db.scalar(select(Escalation.reason_type).where(Escalation.order_id == order.id))
        review_reason = "account" if reason == "credit" else "stock"
    return {
        "order_number": order.order_number,
        "status": order.status,
        "total_amount": float(order.total_amount),
        "currency": order.currency,
        "needs_human_review": order.status == "requires_human_review",
        # "stock": checking availability; "account": the team must approve the order on their account
        "review_reason": review_reason,
    }


_NOT_REGISTERED = {
    "registered": False,
    "message": "This WhatsApp number is not linked to a customer account. The team can help with account questions.",
}


async def _get_my_account(db: AsyncSession, ctx: ToolContext) -> dict:
    customer = await _known_customer(db, ctx)
    if customer is None:
        return _NOT_REGISTERED
    summary = await accounts.account_summary(db, ctx.tenant_id, customer)
    invoices = await accounts.list_invoices(db, ctx.tenant_id, customer_id=customer.id, status_="unpaid", limit=10)
    today = accounts.tenant_today(await db.get(Tenant, ctx.tenant_id))
    await db.commit()
    return {
        "registered": True,
        "customer_name": customer.name,
        "currency": summary["currency"],
        "balance_owed": float(summary["balance"]),
        "credit_limit": float(summary["credit_limit"]) if summary["credit_limit"] is not None else None,
        "available_credit": float(summary["available_credit"]) if summary["available_credit"] is not None else None,
        "overdue_amount": float(summary["overdue"]),
        "payment_terms_days": summary["payment_terms_days"],
        "account_on_hold": summary["on_hold"],
        "credit_on_account": float(summary["unapplied"]),
        "unpaid_invoices": [
            {
                "number": i.number,
                "issue_date": i.issue_date.isoformat(),
                "due_date": i.due_date.isoformat(),
                "total": float(i.total),
                "balance_due": float(i.balance_due),
                "days_overdue": max((today - i.due_date).days, 0),
            }
            for i in invoices
        ],
    }


async def _send_my_statement(db: AsyncSession, ctx: ToolContext, months: int | None, language: str | None) -> dict:
    customer = await _known_customer(db, ctx)
    if customer is None:
        return _NOT_REGISTERED
    months = min(max(int(months or 3), 1), 12)
    end = accounts.tenant_today(await db.get(Tenant, ctx.tenant_id))
    start = end - timedelta(days=30 * months)
    await enqueue(
        db, WHATSAPP_SEND_DOCUMENT,
        {
            "tenant_id": str(ctx.tenant_id), "branch_id": str(ctx.branch_id), "to": ctx.customer_number,
            "doc": "statement", "customer_id": str(customer.id), "start": start.isoformat(), "end": end.isoformat(),
            "language": language or "en",
        },
        tenant_id=ctx.tenant_id, max_attempts=4,
    )
    return {"sent": True, "period_start": start.isoformat(), "period_end": end.isoformat()}


async def _send_invoice_copy(db: AsyncSession, ctx: ToolContext, number: str, language: str | None) -> dict:
    customer = await _known_customer(db, ctx)
    inv = await accounts.find_invoice_by_number(db, ctx.tenant_id, number or "")
    digits = re.sub(r"\D", "", ctx.customer_number or "")
    owner_ok = inv is not None and (
        (customer is not None and inv.customer_id == customer.id)
        or (inv.customer_id is None and digits and re.sub(r"\D", "", (inv.buyer or {}).get("phone") or "") == digits)
    )
    if not owner_ok:
        return {"sent": False, "message": f"No invoice {number} was found for this customer."}
    await enqueue(
        db, WHATSAPP_SEND_DOCUMENT,
        {
            "tenant_id": str(ctx.tenant_id), "branch_id": str(ctx.branch_id), "to": ctx.customer_number,
            "doc": "invoice", "invoice_id": str(inv.id), "language": language or "en",
        },
        tenant_id=ctx.tenant_id, max_attempts=4,
    )
    return {"sent": True, "invoice_number": inv.number}


async def dispatch(db: AsyncSession, ctx: ToolContext, name: str, args: dict) -> dict:
    """Route a tool call from the model to the matching implementation."""
    if name == "search_products":
        return await _search_products(db, ctx.tenant_id, args.get("query", ""))
    if name == "get_price_and_stock":
        return await _get_price_and_stock(db, ctx, args.get("sku", ""))
    if name == "place_order":
        return await _place_order(db, ctx, args.get("items", []), args.get("customer_name"))
    if name == "get_my_account":
        return await _get_my_account(db, ctx)
    if name == "send_my_statement":
        return await _send_my_statement(db, ctx, args.get("months"), args.get("language"))
    if name == "send_invoice_copy":
        return await _send_invoice_copy(db, ctx, args.get("invoice_number", ""), args.get("language"))
    return {"error": f"Unknown tool '{name}'"}