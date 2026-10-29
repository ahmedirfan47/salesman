"""Import all models here so Alembic autogenerate sees them via Base.metadata."""
from app.db.models.accounts import (
    AccountEntry, AccountSettings, CustomerPayment, DocumentCounter, PaymentAllocation, SalesInvoice,
)
from app.db.models.billing import Invoice, Subscription
from app.db.models.branch import Branch
from app.db.models.customer import Customer
from app.db.models.conversation import Conversation
from app.db.models.escalation import Escalation
from app.db.models.integration import IntegrationConnection, IntegrationEvent, IntegrationLink
from app.db.models.inventory import Inventory
from app.db.models.inventory_transaction import InventoryTransaction
from app.db.models.job import Job
from app.db.models.message import Message
from app.db.models.order import Order
from app.db.models.order_event import OrderEvent
from app.db.models.order_item import OrderItem
from app.db.models.platform import AdminAuditLog, LoginEvent, PlatformSettings, UserActivity
from app.db.models.price_list import PriceList
from app.db.models.print_job import PrintJob
from app.db.models.product import Product
from app.db.models.product_price import ProductPrice
from app.db.models.prospect import Prospect, ProspectActivity
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.models.zatca import ZatcaDocument, ZatcaUnit
from app.db.models.zone import DriverZone, Zone

__all__ = [
    "Tenant", "Branch", "User", "Product", "PriceList", "ProductPrice",
    "Inventory", "InventoryTransaction", "Order", "OrderItem", "OrderEvent",
    "Escalation", "PrintJob", "Conversation", "Message", "Zone", "DriverZone", "Customer", "Job",
    "Prospect", "ProspectActivity", "Subscription", "Invoice",
    "AccountSettings", "DocumentCounter", "SalesInvoice", "CustomerPayment", "PaymentAllocation", "AccountEntry",
    "ZatcaUnit", "ZatcaDocument",
    "IntegrationConnection", "IntegrationLink", "IntegrationEvent",
    "PlatformSettings", "UserActivity", "LoginEvent", "AdminAuditLog",
]