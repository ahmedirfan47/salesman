import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    attempts: int = 0


class PrintJobStatusUpdate(BaseModel):
    status: str  # printing | done | failed
    error: str | None = None


class PrintAgentIn(BaseModel):
    branch_id: uuid.UUID
    name: str = Field(min_length=1, max_length=80)


class PrintAgentOut(BaseModel):
    id: uuid.UUID
    name: str
    branch_id: uuid.UUID
    branch_name: str | None
    key_prefix: str
    printer: str | None
    version: str | None
    last_seen_at: datetime | None
    online: bool
    revoked: bool
    created_at: datetime


class PrintAgentCreated(BaseModel):
    agent: PrintAgentOut
    key: str          # shown once: paste it into the agent's config file


class HeartbeatIn(BaseModel):
    printer: str | None = Field(default=None, max_length=120)
    version: str | None = Field(default=None, max_length=32)


class AgentReportIn(BaseModel):
    ok: bool
    error: str | None = Field(default=None, max_length=500)
