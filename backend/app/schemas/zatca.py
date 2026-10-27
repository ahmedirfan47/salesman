import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UnitIn(BaseModel):
    branch_id: uuid.UUID
    environment: Literal["sandbox", "simulation", "production"] = "production"
    location: str = Field(min_length=1, max_length=255, description="the branch's address")
    industry: str = Field(min_length=1, max_length=120, description="e.g. Wholesale of fruit and vegetables")
    invoice_types: Literal["1100", "1000", "0100"] = "1100"
    common_name: str | None = Field(default=None, max_length=64)


class OnboardIn(BaseModel):
    otp: str | None = Field(default=None, max_length=12, description="from the Fatoora portal; valid for about an hour")


class ComplianceResult(BaseModel):
    label: str
    status: str
    errors: list[dict] = []
    warnings: list[dict] = []


class UnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    branch_id: uuid.UUID
    environment: str
    status: str
    common_name: str
    egs_serial: str
    invoice_types: str
    location: str
    industry: str
    icv: int
    has_compliance_certificate: bool = False
    compliance_results: list[ComplianceResult]
    certificate_expires_at: datetime | None
    onboarded_at: datetime | None
    last_error: str | None
    created_at: datetime


class Counts(BaseModel):
    cleared: int
    reported: int
    waiting: int
    rejected: int
    blocked: int


class OverviewOut(BaseModel):
    seller_problems: list[str]
    units: list[UnitOut]
    counts: Counts


class DocumentOut(BaseModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_number: str
    customer_id: uuid.UUID | None
    buyer_name: str | None
    issue_date: date
    currency: str
    total: Decimal
    flow: str
    kind: str
    status: str
    icv: int | None
    document_uuid: str | None
    invoice_hash: str | None
    zatca_status: str | None
    errors: list[dict]
    warnings: list[dict]
    last_error: str | None
    attempts: int
    signed_at: datetime | None
    submitted_at: datetime | None
    created_at: datetime
    has_cleared_xml: bool