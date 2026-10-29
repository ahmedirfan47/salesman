"""Requests to the Stonic Console. Answers are plain JSON built in app.modules.platform.console."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SiteSettingsIn(BaseModel):
    """Only the switches sent are changed."""

    sign_in_enabled: bool | None = None
    sign_up_enabled: bool | None = None
    read_only: bool | None = None
    closed_message: str | None = Field(default=None, max_length=500)
    read_only_message: str | None = Field(default=None, max_length=500)
    banner_text: str | None = Field(default=None, max_length=300)
    banner_tone: str | None = None


class SuspendIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class PersonUpdateIn(BaseModel):
    is_active: bool | None = None
    role: str | None = None


class PasswordIn(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    actor_email: str
    action: str
    target_type: str | None
    target_id: str | None
    target_label: str | None
    detail: dict