import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OrderItemIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    items: list[OrderItemIn] = Field(min_length=1)
    customer_id: uuid.UUID | None = None
    customer_name: str | None = None
    customer_company: str | None = None
    whatsapp_number: str | None = None


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sku: str
    product_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    available_at_order: int | None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_number: str
    status: str
    customer_name: str | None
    customer_company: str | None
    whatsapp_number: str | None
    total_amount: Decimal
    currency: str
    confirmed_at: datetime | None
    created_at: datetime
    zone_id: uuid.UUID | None = None
    assigned_driver_id: uuid.UUID | None = None
    items: list[OrderItemOut]


class EscalationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reason_type: str
    context: dict
    ai_recommendation: str | None
    order_id: uuid.UUID | None
    customer_name: str | None
    status: str
    resolution: str | None
    created_at: datetime


class ResolveEscalation(BaseModel):
    approve: bool
    note: str | None = None


class OrderEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: str | None
    to_status: str
    actor_name: str | None
    note: str | None
    created_at: datetime


class OrderDetailOut(OrderOut):
    events: list[OrderEventOut] = []


class OrderTransition(BaseModel):
    to_status: str
    note: str | None = None