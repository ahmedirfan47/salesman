"""Branch scoping.

Who sees what:
- Owners, admins and demo users see every branch. The dashboard's branch
  switcher sends an `X-Branch-Id` header to narrow everything to one branch;
  without it they see all branches together.
- Everyone else (dispatchers, drivers, warehouse, salesmen, viewers) sees only
  their own branch, whatever header they send. Staff not yet placed in a
  branch see all branches until an admin assigns them.

Routes take `scope: BranchScope` (None = all branches) and filter on it.
Writes that need one concrete branch call `resolve_branch`.
"""
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, DBSession
from app.core.enums import UserRole
from app.db.models.branch import Branch

ALL_BRANCH_ROLES = {UserRole.OWNER.value, UserRole.ADMIN.value, UserRole.DEMO.value}
BRANCH_HEADER = "x-branch-id"


def sees_all_branches(user) -> bool:
    return user.role in ALL_BRANCH_ROLES or user.branch_id is None


async def default_branch(db: AsyncSession, tenant_id: uuid.UUID) -> Branch:
    """The tenant's default branch, created on first use for brand-new tenants."""
    branch = await db.scalar(
        select(Branch).where(Branch.tenant_id == tenant_id, Branch.is_default.is_(True))
    )
    if branch is None:
        branch = Branch(tenant_id=tenant_id, name="Main branch", is_default=True, is_active=True,
                        order_updates_enabled=True)
        db.add(branch)
        await db.flush()
    return branch


async def get_branch(db: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID) -> Branch:
    branch = await db.scalar(select(Branch).where(Branch.id == branch_id, Branch.tenant_id == tenant_id))
    if branch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")
    return branch


async def get_branch_scope(request: Request, user: CurrentUser, db: DBSession) -> uuid.UUID | None:
    if not sees_all_branches(user):
        return user.branch_id
    raw = request.headers.get(BRANCH_HEADER)
    if not raw:
        return None
    try:
        branch_id = uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid branch")
    await get_branch(db, user.tenant_id, branch_id)
    return branch_id


BranchScope = Annotated[uuid.UUID | None, Depends(get_branch_scope)]


def in_scope(scope: uuid.UUID | None, branch_id: uuid.UUID | None) -> bool:
    return scope is None or branch_id == scope


async def resolve_branch(
    db: AsyncSession, tenant_id: uuid.UUID, scope: uuid.UUID | None, requested: uuid.UUID | None = None,
    *, required: bool = False,
) -> uuid.UUID:
    """Pick the one branch a write applies to.

    An explicit branch wins (it must be inside the caller's scope); otherwise the
    caller's current branch; otherwise the default branch -- unless `required`,
    in which case a caller looking at all branches must choose one.
    """
    if requested is not None:
        await get_branch(db, tenant_id, requested)
        if scope is not None and requested != scope:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "That branch is outside your access")
        return requested
    if scope is not None:
        return scope
    if required:
        active = list(await db.scalars(
            select(Branch.id).where(Branch.tenant_id == tenant_id, Branch.is_active.is_(True))
        ))
        if len(active) == 1:
            return active[0]
        if not active:
            return (await default_branch(db, tenant_id)).id
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a branch first")
    return (await default_branch(db, tenant_id)).id