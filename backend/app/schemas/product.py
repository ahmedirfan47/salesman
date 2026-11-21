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


class ProductCatalogRow(BaseModel):
    id: uuid.UUID
    sku: str
    name_en: str
    name_ar: str | None
    category: str | None
    is_active: bool
    unit_price: float | None
    price_min: float | None = None
    price_max: float | None = None
    currency: str | None
    stock: int

class ProductAliasIn(BaseModel):
    alias: str = Field(min_length=2, max_length=200)
    # set to make the alias apply to one customer's messages only
    customer_id: uuid.UUID | None = None


class ProductAliasOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    product_name: str
    alias: str
    customer_id: uuid.UUID | None
    customer_name: str | None
    source: str
    hits: int
    last_used_at: datetime | None
    created_at: datetime


class ProductMatchOut(BaseModel):
    product_id: uuid.UUID
    sku: str
    name_en: str
    name_ar: str | None
    score: float
    matched_by: str
