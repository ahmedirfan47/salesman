import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class Zone(UUIDPKMixin, TimestampMixin, Base):
    """A delivery area/zone, e.g. 'Riyadh North'."""

    __tablename__ = "zones"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_zone_tenant_name"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)


class DriverZone(UUIDPKMixin, TimestampMixin, Base):
    """Which drivers cover which zones (many-to-many)."""

    __tablename__ = "driver_zones"
    __table_args__ = (UniqueConstraint("driver_id", "zone_id", name="uq_driver_zone"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    driver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zones.id", ondelete="CASCADE"), index=True, nullable=False
    )