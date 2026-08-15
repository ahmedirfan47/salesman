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
    DISPATCH_ORDER = "dispatch_order"
    DELIVER_ORDER = "deliver_order"
    COMPLETE_ORDER = "complete_order"
    CANCEL_ORDER = "cancel_order"
    VIEW_REPORTS = "view_reports"
    VIEW_PRINTING = "view_printing"
    VIEW_CONVERSATIONS = "view_conversations"


_ALL = set(Capability)

ROLE_CAPABILITIES: dict[UserRole, set[Capability]] = {
    UserRole.OWNER: set(_ALL),
    UserRole.ADMIN: set(_ALL),
    UserRole.SALESMAN: {
        Capability.CREATE_ORDER,
        Capability.VIEW_ORDERS,
        Capability.VIEW_CONVERSATIONS,
        Capability.VIEW_REPORTS,
    },
    UserRole.DISPATCHER: {
        Capability.VIEW_ORDERS,
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
        Capability.DISPATCH_ORDER,
    },
    UserRole.VIEWER: {
        Capability.VIEW_ORDERS,
        Capability.VIEW_REPORTS,
    },
}


def capabilities_for(role: str) -> set[Capability]:
    try:
        return ROLE_CAPABILITIES.get(UserRole(role), set())
    except ValueError:
        return set()


def has_capability(role: str, cap: Capability) -> bool:
    return cap in capabilities_for(role)