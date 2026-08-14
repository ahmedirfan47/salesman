import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name_en: str = Field(min_length=1, max_length=255)
    name_ar: str | None = None
    description: str | None = None
    category: str | None = None
    is_active: bool = True


class ProductUpdate(BaseModel):
    name_en: str | None = Field(default=None, max_length=255)
    name_ar: str | None = None
    description: str | None = None
    category: str | None = None
    is_active: bool | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    sku: str
    name_en: str
    name_ar: str | None
    description: str | None
    category: str | None
    is_active: bool
    created_at: datetime