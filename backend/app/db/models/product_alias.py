import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class ProductAlias(UUIDPKMixin, TimestampMixin, Base):
    """Another name a customer uses for a product: "the red one", "حليب صغير",
    a brand nickname, a typo that keeps coming back.

    The AI looks aliases up before it searches product names, so an order that
    was corrected once is understood the next time. An alias can belong to one
    customer (only their messages use it) or to the whole business
    (customer_id NULL).

    source: manual (typed by staff) | learned (the customer confirmed an order
    with these words) | correction (staff corrected the AI's choice).
    `alias_norm` is the normalised form used for matching (see
    app.modules.products.matching.normalise).
    """

    __tablename__ = "product_aliases"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "customer_id", "alias_norm",
            name="uq_product_alias", postgresql_nulls_not_distinct=True,
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=True
    )
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    alias_norm: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    hits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
