import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CustomerCreate(BaseModel):
    name: str
    company: str | None = None
    whatsapp_number: str | None = None
    address: str | None = None
    zone_id: uuid.UUID | None = None


class CustomerUpdate(BaseModel):
    name: str | None = None
    company: str | None = None
    whatsapp_number: str | None = None
    address: str | None = None
    zone_id: uuid.UUID | None = None
    is_active: bool | None = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    company: str | None
    whatsapp_number: str | None
    address: str | None
    zone_id: uuid.UUID | None
    is_active: bool
    created_at: datetime