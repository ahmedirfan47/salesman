"""Import all models here so Alembic autogenerate sees them via Base.metadata."""

from app.db.models.escalation import Escalation
from app.db.models.inventory import Inventory
from app.db.models.inventory_transaction import InventoryTransaction
from app.db.models.order import Order
from app.db.models.order_item import OrderItem
from app.db.models.price_list import PriceList
from app.db.models.product import Product
from app.db.models.product_price import ProductPrice
from app.db.models.tenant import Tenant
from app.db.models.user import User

__all__ = [
    "Tenant",
    "User",
    "Product",
    "PriceList",
    "ProductPrice",
    "Inventory",
    "InventoryTransaction",
    "Order",
    "OrderItem",
    "Escalation",
]