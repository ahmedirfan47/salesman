import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class CustomerPriceIn(BaseModel):
    customer_id: uuid.UUID
    sku: str = Field(min_length=1, max_length=64)
    unit_price: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    branch_id: uuid.UUID | None = None
    min_quantity: int = Field(default=1, ge=1, le=1_000_000)
    valid_from: date | None = None
    valid_to: date | None = None
    note: str | None = Field(default=None, max_length=255)


class CustomerPriceOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str
    product_id: uuid.UUID
    sku: str
    product_name: str
    branch_id: uuid.UUID | None
    unit_price: Decimal
    min_quantity: int
    valid_from: date | None
    valid_to: date | None
    note: str | None
    created_at: datetime


class PromotionIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    kind: Literal["percent_off", "fixed_price", "buy_get"]
    sku: str = Field(min_length=1, max_length=64)
    branch_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    min_quantity: int = Field(default=1, ge=1, le=1_000_000)
    percent_off: Decimal | None = Field(default=None, gt=0, lt=100)
    fixed_price: Decimal | None = Field(default=None, ge=0)
    buy_quantity: int | None = Field(default=None, ge=1)
    free_quantity: int | None = Field(default=None, ge=1)
    free_sku: str | None = Field(default=None, max_length=64)
    starts_on: date | None = None
    ends_on: date | None = None
    is_active: bool = True


class PromotionOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    summary: str
    live: bool
    product_id: uuid.UUID
    sku: str | None
    product_name: str | None
    branch_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    customer_name: str | None
    min_quantity: int
    percent_off: Decimal | None
    fixed_price: Decimal | None
    buy_quantity: int | None
    free_quantity: int | None
    free_sku: str | None
    starts_on: date | None
    ends_on: date | None
    is_active: bool


class FreeOut(BaseModel):
    sku: str
    name: str
    quantity: int
    promotion: str


class QuoteOut(BaseModel):
    sku: str
    quantity: int
    list_price: Decimal
    unit_price: Decimal
    source: str
    promotion: str | None
    line_total: Decimal
    free: list[FreeOut]
