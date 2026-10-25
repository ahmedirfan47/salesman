import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MarginSummaryOut(_Out):
    days: int
    currency: str | None
    revenue: float
    order_count: int
    costed_revenue: float
    costed_cost: float
    costed_profit: float
    margin_percent: float | None
    cost_coverage_percent: float
    products_missing_cost: int


class ProductMarginOut(_Out):
    sku: str
    name: str
    units_sold: int
    revenue: float
    cost: float
    profit: float
    margin_percent: float | None


class DriftingCustomerOut(_Out):
    customer_id: uuid.UUID
    name: str
    last_order_at: datetime | None
    days_since_last_order: int
    typical_gap_days: float | None
    order_count: int


class StuckOrderOut(_Out):
    order_id: uuid.UUID
    order_number: str
    status: str
    customer_name: str | None
    hours_in_status: float
    threshold_hours: int


class ProductCostOut(_Out):
    product_id: uuid.UUID
    sku: str
    name: str
    is_active: bool
    cost_price: float | None
    cost_currency: str | None
    sell_price: float | None
    sell_currency: str | None
    current_margin_percent: float | None


class ProductCostIn(BaseModel):
    product_id: uuid.UUID
    # None clears the cost (margin returns to "unknown" for future orders).
    cost_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    cost_currency: str | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("cost_currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class ProductCostBulkIn(BaseModel):
    items: list[ProductCostIn] = Field(min_length=1, max_length=500)


class ProductCostBulkResult(BaseModel):
    updated: int