from enum import Enum


class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    WAREHOUSE = "warehouse"
    VIEWER = "viewer"


# Higher number => more privileges. Used for RBAC "minimum role" checks.
ROLE_HIERARCHY: dict[UserRole, int] = {
    UserRole.VIEWER: 0,
    UserRole.WAREHOUSE: 1,
    UserRole.ADMIN: 2,
    UserRole.OWNER: 3,
}