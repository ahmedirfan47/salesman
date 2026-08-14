import uuid

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class Inventory(UUIDPKMixin, TimestampMixin, Base):
    """Cached current stock level per product (one row per product).

    This is the fast 'how many do we have right now' value. It is always
    updated inside the same DB transaction as an InventoryTransaction, so
    it can never drift from the ledger.
    """

    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", name="uq_inventory_tenant_product"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False
    )
    quantity_on_hand: Mapped[int] = mapped_column(Integer, default=0, nullable=False)