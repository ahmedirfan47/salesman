import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ---- input ----
class PriceLineIn(BaseModel):
    """One row from the daily sheet: a product's price and available quantity."""
    sku: str = Field(min_length=1, max_length=64)
    unit_price: Decimal = Field(ge=0)
    quantity: int = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    # optional: what the product costs the business (from a "Cost" column)
    unit_cost: Decimal | None = Field(default=None, ge=0)
    # optional: create the product on the fly if the SKU is new
    name_en: str | None = None
    name_ar: str | None = None


class PriceListCreate(BaseModel):
    source_filename: str | None = None
    lines: list[PriceLineIn] = Field(default_factory=list)


# ---- output ----
class PriceListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    branch_id: uuid.UUID
    version: int
    source_filename: str | None
    status: str
    activated_at: datetime | None
    superseded_at: datetime | None
    created_at: datetime


class ProductPriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    branch_id: uuid.UUID
    price_list_id: uuid.UUID
    unit_price: Decimal
    currency: str
    effective_from: datetime
    effective_to: datetime | None


class CurrentPriceOut(BaseModel):
    """The agent-facing view: current price + current stock for a product."""
    product_id: uuid.UUID
    sku: str
    name_en: str
    unit_price: Decimal
    currency: str
    quantity_on_hand: int
    price_list_version: int
    effective_from: datetime