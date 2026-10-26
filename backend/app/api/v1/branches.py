"""Branches: list for everyone (staff see only their own); manage for admins."""
import uuid

from fastapi import APIRouter, Depends, status

from app.core.branches import sees_all_branches
from app.core.deps import CurrentUser, DBSession, require_capability
from app.core.permissions import Capability
from app.modules.branches import service
from app.modules.notifications.service import TEMPLATE_HINT
from app.schemas.branch import BranchCreate, BranchOut, BranchSetupOut, BranchUpdate

router = APIRouter(prefix="/branches", tags=["branches"])

_manage = Depends(require_capability(Capability.MANAGE_USERS))


@router.get("", response_model=list[BranchOut])
async def list_branches(db: DBSession, user: CurrentUser) -> list[BranchOut]:
    only = None if sees_all_branches(user) else user.branch_id
    return [BranchOut.model_validate(service.to_out(b)) for b in await service.list_branches(db, user.tenant_id, only)]


@router.get("/whatsapp-setup", response_model=BranchSetupOut, dependencies=[_manage])
async def whatsapp_setup() -> BranchSetupOut:
    """The template to submit in Meta for order updates sent outside the 24-hour window."""
    return BranchSetupOut(
        template_category="UTILITY",
        template_body_en=TEMPLATE_HINT["en"],
        template_body_ar=TEMPLATE_HINT["ar"],
        webhook_path="/api/v1/webhooks/whatsapp",
    )


@router.post("", response_model=BranchOut, status_code=status.HTTP_201_CREATED, dependencies=[_manage])
async def create_branch(data: BranchCreate, db: DBSession, user: CurrentUser) -> BranchOut:
    branch = await service.create_branch(db, user.tenant_id, data.model_dump())
    return BranchOut.model_validate(service.to_out(branch))


@router.patch("/{branch_id}", response_model=BranchOut, dependencies=[_manage])
async def update_branch(branch_id: uuid.UUID, data: BranchUpdate, db: DBSession, user: CurrentUser) -> BranchOut:
    branch = await service.update_branch(db, user.tenant_id, branch_id, data.model_dump(exclude_unset=True))
    return BranchOut.model_validate(service.to_out(branch))