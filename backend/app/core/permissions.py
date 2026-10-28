"""Capability-based permissions.

Each role maps to a set of capabilities. Endpoints gate on capabilities (not on
role hierarchy), so we can model real jobs -- a driver isn't "less than" a
dispatcher, they just have different capabilities.
"""
from enum import Enum

from app.core.enums import UserRole


class Capability(str, Enum):
    MANAGE_USERS = "manage_users"
    MANAGE_PRODUCTS = "manage_products"
    MANAGE_PRICING = "manage_pricing"
    CREATE_ORDER = "create_order"
    VIEW_ORDERS = "view_orders"
    RESOLVE_ESCALATION = "resolve_escalation"
    PREPARE_ORDER = "prepare_order"
    DISPATCH_ORDER = "dispatch_order"
    DELIVER_ORDER = "deliver_order"
    COMPLETE_ORDER = "complete_order"
    CANCEL_ORDER = "cancel_order"
    VIEW_REPORTS = "view_reports"
    VIEW_PRINTING = "view_printing"
    VIEW_CONVERSATIONS = "view_conversations"
    # Margins, costs and customer-health data are commercially sensitive, so
    # they get their own capability rather than riding on VIEW_REPORTS
    # (which salesmen and viewers have). Owner/admin only, via _ALL.
    VIEW_ANALYTICS = "view_analytics"
    # Finding new shops, win-back outreach and the prospect pipeline.
    MANAGE_PROSPECTS = "manage_prospects"
    # The business's own subscription and invoices from Stonic.
    VIEW_BILLING = "view_billing"
    # Customer accounts: balances, invoices, statements and credit status.
    VIEW_ACCOUNTS = "view_accounts"
    # Record payments, issue credit notes, set credit limits and terms.
    MANAGE_ACCOUNTS = "manage_accounts"
    # Connect an ERP or accounting system (Odoo, ...) and control what syncs.
    MANAGE_INTEGRATIONS = "manage_integrations"


_ALL = set(Capability)

ROLE_CAPABILITIES: dict[UserRole, set[Capability]] = {
    UserRole.OWNER: set(_ALL),
    UserRole.ADMIN: set(_ALL),
    # Demo sees every screen; app.core.deps blocks all writes for this role.
    UserRole.DEMO: set(_ALL),
    UserRole.SALESMAN: {
        Capability.CREATE_ORDER,
        Capability.VIEW_ORDERS,
        Capability.VIEW_CONVERSATIONS,
        Capability.VIEW_REPORTS,
        Capability.MANAGE_PROSPECTS,
        Capability.VIEW_ACCOUNTS,
    },
    UserRole.DISPATCHER: {
        Capability.VIEW_ORDERS,
        Capability.PREPARE_ORDER,
        Capability.DISPATCH_ORDER,
        Capability.CANCEL_ORDER,
        Capability.VIEW_PRINTING,
    },
    UserRole.DRIVER: {
        Capability.VIEW_ORDERS,
        Capability.DELIVER_ORDER,
        Capability.COMPLETE_ORDER,
    },
    UserRole.WAREHOUSE: {
        Capability.VIEW_ORDERS,
        Capability.VIEW_PRINTING,
        Capability.PREPARE_ORDER,
        Capability.DISPATCH_ORDER,
    },
    UserRole.VIEWER: {
        Capability.VIEW_ORDERS,
        Capability.VIEW_REPORTS,
        Capability.VIEW_ACCOUNTS,
    },
}


def capabilities_for(role: str) -> set[Capability]:
    try:
        return ROLE_CAPABILITIES.get(UserRole(role), set())
    except ValueError:
        return set()


def has_capability(role: str, cap: Capability) -> bool:
    return cap in capabilities_for(role)