import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class CustomerPrice(UUIDPKMixin, TimestampMixin, Base):
    """A price agreed with one customer for one product.

    Optional limits: one branch (NULL = every branch), a minimum quantity per
    order line (tiers: 1+ at 95, 10+ at 90), and dates. The most specific row
    that applies wins: this branch before all branches, then the highest
    minimum quantity reached. See app.modules.deals.service.
    """

    __tablename__ = "customer_prices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_id", "product_id", "branch_id", "min_quantity",
                         name="uq_customer_price", postgresql_nulls_not_distinct=True),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=True
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    min_quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Promotion(UUIDPKMixin, TimestampMixin, Base):
    """A deal on one product.

    kind:
      percent_off -- `percent_off` % off the list price
      fixed_price -- the line is sold at `fixed_price` per unit
      buy_get     -- for every `buy_quantity` bought, `free_quantity` of
                     `free_product_id` (or the same product) is added free
    Limits: a minimum quantity on the line, dates, one branch and/or one
    customer (NULL = everyone). Price deals don't stack: the customer gets the
    lowest of their own price and every price deal that applies. Free goods
    come on top, from the single best buy_get deal for the product.
    """

    __tablename__ = "promotions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=True
    )
    min_quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    percent_off: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    fixed_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    buy_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    free_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    free_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=True
    )
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
