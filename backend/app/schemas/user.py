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
    created_at: datetime


class MeOut(UserOut):
    capabilities: list[str] = []


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    role: str = "salesman"


class UserRoleUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None