import uuid

from fastapi import APIRouter, Depends, status

from app.core.branches import BranchScope
from app.core.deps import CurrentUser, DBSession, require_capability
from app.core.permissions import Capability
from app.modules.customers import service
from app.schemas.customer import CustomerCreate, CustomerOut, CustomerUpdate

router = APIRouter(prefix="/customers", tags=["customers"])

# managing customers = admin-level (same capability as user management)
_manage = Depends(require_capability(Capability.MANAGE_USERS))


@router.get("", response_model=list[CustomerOut])
async def list_customers(db: DBSession, user: CurrentUser, scope: BranchScope) -> list[CustomerOut]:
    return await service.list_customers(db, user.tenant_id, scope)


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED, dependencies=[_manage])
async def create_customer(data: CustomerCreate, db: DBSession, user: CurrentUser, scope: BranchScope) -> CustomerOut:
    return await service.create_customer(
        db, user.tenant_id, name=data.name, company=data.company,
        whatsapp_number=data.whatsapp_number, address=data.address, zone_id=data.zone_id,
        branch_id=data.branch_id, scope=scope,
    )


@router.patch("/{customer_id}", response_model=CustomerOut, dependencies=[_manage])
async def update_customer(
    customer_id: uuid.UUID, data: CustomerUpdate, db: DBSession, user: CurrentUser, scope: BranchScope
) -> CustomerOut:
    return await service.update_customer(
        db, user.tenant_id, customer_id, scope=scope, **data.model_dump(exclude_unset=True)
    )