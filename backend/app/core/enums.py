from enum import Enum


class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    SALESMAN = "salesman"
    DISPATCHER = "dispatcher"
    DRIVER = "driver"
    WAREHOUSE = "warehouse"
    VIEWER = "viewer"


# Kept for backward-compatible require_role() checks. Job roles sit at a low
# level; real gating is done via capabilities (see permissions.py).
ROLE_HIERARCHY: dict[UserRole, int] = {
    UserRole.VIEWER: 0,
    UserRole.DRIVER: 1,
    UserRole.SALESMAN: 1,
    UserRole.DISPATCHER: 1,
    UserRole.WAREHOUSE: 1,
    UserRole.ADMIN: 2,
    UserRole.OWNER: 3,
}