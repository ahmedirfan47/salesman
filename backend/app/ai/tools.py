"""Agent tools. Each tool wraps a real service call against the tenant's data,
so the model can look up TRUE prices/stock and place orders -- never guess.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _get_price_and_stock(db: AsyncSession, tenant_id: uuid.UUID, sku: str) -> dict:
    result = await pricing_service.get_current_price(db, tenant_id, sku)
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


async def _place_order(
    db: AsyncSession, tenant_id: uuid.UUID, items: list[dict], customer_name: str | None = None
) -> dict:
    order = await orders_service.create_order(
        db,
        tenant_id,
        OrderCreate(
            items=[OrderItemIn(sku=i["sku"], quantity=int(i["quantity"])) for i in items],
            customer_name=customer_name,
        ),
    )
    return {
        "order_number": order.order_number,
        "status": order.status,
        "total_amount": float(order.total_amount),
        "currency": order.currency,
        "needs_human_review": order.status == "requires_human_review",
    }


async def dispatch(
    db: AsyncSession, tenant_id: uuid.UUID, name: str, args: dict
) -> dict:
    """Route a tool call from the model to the matching implementation."""
    if name == "search_products":
        return await _search_products(db, tenant_id, args.get("query", ""))
    if name == "get_price_and_stock":
        return await _get_price_and_stock(db, tenant_id, args.get("sku", ""))
    if name == "place_order":
        return await _place_order(
            db, tenant_id, args.get("items", []), args.get("customer_name")
        )
    return {"error": f"Unknown tool '{name}'"}