import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BranchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    is_default: bool = False
    whatsapp_phone_number_id: str | None = Field(default=None, max_length=64)
    whatsapp_access_token: str | None = Field(default=None, max_length=512)
    whatsapp_display_number: str | None = Field(default=None, max_length=32)
    whatsapp_update_template: str | None = Field(default=None, max_length=120)
    order_updates_enabled: bool = True


class BranchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    is_default: bool | None = None
    is_active: bool | None = None
    whatsapp_phone_number_id: str | None = Field(default=None, max_length=64)
    # write-only; send "" to remove it
    whatsapp_access_token: str | None = Field(default=None, max_length=512)
    whatsapp_display_number: str | None = Field(default=None, max_length=32)
    whatsapp_update_template: str | None = Field(default=None, max_length=120)
    order_updates_enabled: bool | None = None


class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    city: str | None
    address: str | None
    is_default: bool
    is_active: bool
    whatsapp_phone_number_id: str | None
    whatsapp_display_number: str | None
    whatsapp_update_template: str | None
    whatsapp_connected: bool
    order_updates_enabled: bool
    created_at: datetime


class BranchSetupOut(BaseModel):
    """What to submit to Meta for the order-update template."""
    template_category: str
    template_body_en: str
    template_body_ar: str
    webhook_path: str