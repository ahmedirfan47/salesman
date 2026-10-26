"""Agent tools. Each tool wraps a real service call against the tenant's data,
so the model can look up TRUE prices/stock and place orders -- never guess.

Tools run in the context of one branch (the branch whose WhatsApp number the
customer wrote to) and, when known, the customer's own number.
"""
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.customer import Customer
from app.db.models.product import Product
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
    return {
        "order_number": order.order_number,
        "status": order.status,
        "total_amount": float(order.total_amount),
        "currency": order.currency,
        "needs_human_review": order.status == "requires_human_review",
    }


async def dispatch(db: AsyncSession, ctx: ToolContext, name: str, args: dict) -> dict:
    """Route a tool call from the model to the matching implementation."""
    if name == "search_products":
        return await _search_products(db, ctx.tenant_id, args.get("query", ""))
    if name == "get_price_and_stock":
        return await _get_price_and_stock(db, ctx, args.get("sku", ""))
    if name == "place_order":
        return await _place_order(db, ctx, args.get("items", []), args.get("customer_name"))
    return {"error": f"Unknown tool '{name}'"}