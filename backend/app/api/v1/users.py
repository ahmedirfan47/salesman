import uuid

from fastapi import APIRouter, Depends, status

from app.core.deps import CurrentUser, DBSession, require_capability
from app.core.permissions import Capability
from app.modules.users import service
from app.schemas.user import UserCreate, UserOut, UserRoleUpdate

router = APIRouter(prefix="/users", tags=["users"])

_admin = Depends(require_capability(Capability.MANAGE_USERS))


@router.get("", response_model=list[UserOut], dependencies=[_admin])
async def list_users(db: DBSession, user: CurrentUser) -> list[UserOut]:
    return await service.list_users(db, user.tenant_id)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED, dependencies=[_admin])
async def create_user(data: UserCreate, db: DBSession, user: CurrentUser) -> UserOut:
    return await service.create_user(
        db, user.tenant_id, email=data.email, password=data.password,
        full_name=data.full_name, role=data.role, branch_id=data.branch_id,
    )


@router.patch("/{user_id}", response_model=UserOut, dependencies=[_admin])
async def update_user(
    user_id: uuid.UUID, data: UserRoleUpdate, db: DBSession, user: CurrentUser
) -> UserOut:
    fields = data.model_dump(exclude_unset=True)
    return await service.update_user(
        db, user.tenant_id, user_id, role=data.role, is_active=data.is_active,
        acting_user_id=user.id, branch_id=data.branch_id, set_branch="branch_id" in fields,
    )