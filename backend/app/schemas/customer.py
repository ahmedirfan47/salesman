import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CustomerCreate(BaseModel):
    name: str
    company: str | None = None
    whatsapp_number: str | None = None
    address: str | None = None
    zone_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None  # defaults to the zone's branch, else your branch
    vat_number: str | None = None


class CustomerUpdate(BaseModel):
    name: str | None = None
    company: str | None = None
    whatsapp_number: str | None = None
    address: str | None = None
    zone_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    is_active: bool | None = None
    vat_number: str | None = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    branch_id: uuid.UUID
    name: str
    company: str | None
    whatsapp_number: str | None
    address: str | None
    zone_id: uuid.UUID | None
    is_active: bool
    created_at: datetime
    # credit terms are edited on the Accounts page (PATCH /accounts/customers/{id}/credit)
    vat_number: str | None = None
    credit_limit: Decimal | None = None
    payment_terms_days: int | None = None
    on_hold: bool = False
    # tax registration and national address, edited on the Accounts page (PATCH .../tax-details)
    cr_number: str | None = None
    street: str | None = None
    building_number: str | None = None
    district: str | None = None
    city: str | None = None
    postal_code: str | None = None