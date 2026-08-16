import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ZoneCreate(BaseModel):
    name: str
    description: str | None = None


class ZoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime


class DriverZonesUpdate(BaseModel):
    zone_ids: list[uuid.UUID]


class OrderAssign(BaseModel):
    zone_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None