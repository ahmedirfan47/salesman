import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ZoneCreate(BaseModel):
    name: str
    description: str | None = None
    branch_id: uuid.UUID | None = None  # defaults to the branch you're working in


class ZoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    branch_id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime


class DriverZonesUpdate(BaseModel):
    zone_ids: list[uuid.UUID]


class OrderAssign(BaseModel):
    zone_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None