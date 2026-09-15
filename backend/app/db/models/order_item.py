import uuid

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class OrderItem(UUIDPKMixin, TimestampMixin, Base):
    """One line in an order. Price is SNAPSHOTTED at order time so later price
    changes never rewrite what the customer was actually charged."""

    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)

    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)

    # Cost SNAPSHOTTED at order time (mirrors unit_price above) -- so a later
    # change to Product.cost_price never rewrites a past order's margin.
    # Nullable: orders placed before this field existed, or for a product
    # with no cost set, correctly have no cost data rather than a fake 0.
    unit_cost: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)

    # what the item needed vs had, for the human-review case
    available_at_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    order = relationship("Order", back_populates="items")