import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PrintJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    status: str
    location: str | None
    payload: dict
    error: str | None
    printed_at: datetime | None
    created_at: datetime


class PrintJobStatusUpdate(BaseModel):
    status: str  # printing | done | failed
    error: str | None = None