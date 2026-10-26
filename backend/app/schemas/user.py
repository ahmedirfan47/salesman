import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: str
    is_active: bool
    branch_id: uuid.UUID | None = None
    created_at: datetime


class MeOut(UserOut):
    capabilities: list[str] = []
    branch_name: str | None = None
    sees_all_branches: bool = True
    # billing: 'ok' | 'open' | 'overdue' | 'read_only', and a notice to show (if any)
    billing_state: str = "ok"
    billing_message: str | None = None
    is_platform_admin: bool = False


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    role: str = "salesman"
    branch_id: uuid.UUID | None = None  # required for branch staff; owners/admins see all


class UserRoleUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    branch_id: uuid.UUID | None = None  # send null to clear