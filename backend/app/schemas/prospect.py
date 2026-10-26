import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ProspectStatus = Literal["new", "contacted", "interested", "won", "lost"]
Language = Literal["en", "ar"]


# ---- input ----
class ProspectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    area: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=64)
    zone_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)
    assigned_to_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None


class ProspectUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, max_length=500)
    area: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=64)
    zone_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)
    status: ProspectStatus | None = None
    lost_reason: str | None = Field(default=None, max_length=255)
    assigned_to_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None


class PlaceAdd(BaseModel):
    place_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
    maps_uri: str | None = Field(default=None, max_length=500)
    area: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=64)
    zone_id: uuid.UUID | None = None


class DraftIn(BaseModel):
    language: Language = "en"


class ContactedIn(BaseModel):
    message: str | None = Field(default=None, max_length=4000)


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ConvertIn(BaseModel):
    zone_id: uuid.UUID | None = None


# ---- output ----
class ProspectOut(BaseModel):
    id: uuid.UUID
    branch_id: uuid.UUID | None
    kind: Literal["new", "winback"]
    source: str
    status: ProspectStatus
    name: str
    contact_name: str | None
    phone: str | None
    phone_digits: str | None
    address: str | None
    area: str | None
    category: str | None
    zone_id: uuid.UUID | None
    zone_name: str | None
    google_maps_uri: str | None
    insight: str | None
    notes: str | None
    lost_reason: str | None
    assigned_to_id: uuid.UUID | None
    assigned_to_name: str | None
    customer_id: uuid.UUID | None
    last_contacted_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    priority: Literal["high", "medium", "low"]
    priority_reasons: list[str]


class ActivityOut(BaseModel):
    id: uuid.UUID
    kind: str
    body: str | None
    actor_name: str | None
    created_at: datetime


class ProspectDetailOut(ProspectOut):
    activities: list[ActivityOut]


class Assignee(BaseModel):
    id: uuid.UUID
    name: str | None


class ProspectSummaryOut(BaseModel):
    counts: dict[str, int]
    open_new: int
    open_winback: int
    google_search_enabled: bool
    assignees: list[Assignee]


class DraftOut(BaseModel):
    message: str
    language: Language
    source: Literal["ai", "template"]


class SkippedRow(BaseModel):
    row: int
    name: str | None
    reason: str


class ImportResultOut(BaseModel):
    created: int
    skipped: list[SkippedRow]


class WinbackRefreshOut(BaseModel):
    created: int
    closed: int


class PlaceResult(BaseModel):
    place_id: str
    name: str
    address: str | None
    phone: str | None
    phone_display: str | None
    maps_uri: str | None
    rating: float | None
    rating_count: int | None
    temporarily_closed: bool
    already_prospect: bool
    already_customer: bool


class PlaceSearchOut(BaseModel):
    results: list[PlaceResult]
    next_page_token: str | None