"""Who may use Salesman right now: one check shared by sign-in, token refresh and every request."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.modules.platform import site

INACTIVE = "This account has been switched off. Ask your administrator."
SUSPENDED = "This business's Salesman account is suspended. Please contact Stonic."
SESSION_ENDED = "Your session has ended. Please sign in again."


def is_platform_admin(user: User | None) -> bool:
    from app.modules.billing.service import is_platform_admin as check

    return check(user)


async def blocked(db: AsyncSession, user: User) -> tuple[str, str] | None:
    """(reason, message) when this person may not sign in or stay signed in; None when they may."""
    if not user.is_active:
        return "inactive", INACTIVE
    if is_platform_admin(user):
        return None
    values = await site.effective(db)
    if not values["sign_in_enabled"]:
        return "sign_in_closed", values["closed_message"]
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is not None and tenant.suspended_at is not None:
        return "suspended", SUSPENDED
    return None


async def read_only_message(db: AsyncSession, user: User) -> str | None:
    """The message to refuse a change with while the whole site is read-only (None otherwise)."""
    if is_platform_admin(user):
        return None
    values = await site.effective(db)
    return values["read_only_message"] if values["read_only"] else None