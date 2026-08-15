from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class Tenant(UUIDPKMixin, TimestampMixin, Base):
    """A client business using Salesman. Root of all tenant-scoped data."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    business_rules: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    whatsapp_phone_number_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    whatsapp_access_token: Mapped[str | None] = mapped_column(String(512), nullable=True)

    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")