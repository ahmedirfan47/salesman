import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProviderOut(BaseModel):
    key: str
    name: str
    available: bool
    # what the connect form asks for, per field: label, placeholder, optional, default
    connect_fields: dict = {}


class ConnectIn(BaseModel):
    provider: str = "odoo"
    url: str | None = Field(default=None, max_length=255)
    tenant: str | None = Field(default=None, max_length=120)      # Business Central: Microsoft Entra tenant
    database: str | None = Field(default=None, max_length=120)
    username: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=255)   # empty: keep the saved key


Ref = int | str   # Odoo and SAP price lists use numbers; SAP codes and Business Central ids are strings


class BranchMapping(BaseModel):
    warehouse_id: Ref | None = None
    pricelist_id: Ref | None = None


class SettingsIn(BaseModel):
    company_id: Ref | None = None
    sales_journal_id: Ref | None = None
    taxes: dict[str, Ref | None] | None = None
    payment_journals: dict[str, Ref | None] | None = None
    adjustment_account: Ref | None = None    # SAP and Business Central: account for lines without an item
    branches: dict[str, BranchMapping] | None = None
    push_orders: bool | None = None
    validate_deliveries: bool | None = None
    push_invoices: bool | None = None
    push_payments: bool | None = None
    pull_catalog: bool | None = None
    pull_interval_minutes: int | None = Field(default=None, ge=5, le=1440)


class ConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    status: str
    base_url: str
    database: str | None
    username: str | None
    api: str | None
    server_version: str | None
    settings: dict
    connected_at: datetime | None
    last_pull_at: datetime | None
    next_pull_at: datetime | None
    last_error: str | None
    created_at: datetime


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    direction: str
    action: str
    local_key: str
    label: str
    status: str
    message: str | None
    external_ref: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime


class Counts(BaseModel):
    ok: int = 0
    warning: int = 0
    failed: int = 0
    skipped: int = 0


class OverviewOut(BaseModel):
    providers: list[ProviderOut]
    connection: ConnectionOut | None
    problems: list[str] = []
    counts: Counts = Counts()


class ConnectOut(BaseModel):
    connection: ConnectionOut
    options: dict
    problems: list[str]


class BalanceOut(BaseModel):
    customer_id: uuid.UUID
    name: str | None
    salesman: Decimal
    odoo: Decimal            # the ERP's balance (named for the first connector; same as `erp`)
    erp: Decimal | None = None
    difference: Decimal
    partner_id: int | str


class TestOut(BaseModel):
    ok: bool
    kind: str
    message: str
    latency_ms: int
    version: str | None = None
    companies: int | None = None
    warehouses: int | None = None
    price_lists: int | None = None
    taxes: int | None = None
    problems: list[str] = []


class HealthCheck(BaseModel):
    key: str
    status: str
    message: str


class HealthOut(BaseModel):
    status: str              # healthy | degraded | down | off
    checks: list[HealthCheck]
    checked_at: datetime