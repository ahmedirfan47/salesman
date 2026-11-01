"""Stonic's own records about the platform: admin accounts, site switches, usage and an audit trail.

None of these belong to a business. They are read and changed only through
the Stonic Console (/console in the dashboard; app.api.v1.console and admin).
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPKMixin


class PlatformAdmin(UUIDPKMixin, TimestampMixin, Base):
    """A Stonic staff account for the Stonic Console. Not part of any business.

    The first one is made with `python -m app.scripts.create_admin`; after that,
    admins add each other from the console.
    """

    __tablename__ = "platform_admins"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Raising this ends every console session of this admin.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class PlatformSettings(Base):
    """The site switches (sign-in, sign-up, read-only, banner). Always one row, id = 1."""

    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)


class UserActivity(Base):
    """One row per person, per day, per client (web dashboard or mobile app) they used."""

    __tablename__ = "user_activity"
    __table_args__ = (Index("ix_user_activity_day", "day"),)

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    client: Mapped[str] = mapped_column(String(10), primary_key=True)  # web | mobile | api
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )


class LoginEvent(UUIDPKMixin, TimestampMixin, Base):
    """Every sign-in attempt, successful or not."""

    __tablename__ = "login_events"
    __table_args__ = (Index("ix_login_events_created_at", "created_at"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    client: Mapped[str] = mapped_column(String(10), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # ok | wrong_password | unknown_email | inactive | suspended | sign_in_closed
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AdminAuditLog(UUIDPKMixin, TimestampMixin, Base):
    """Every change made from the Stonic Console, and who made it (plus console sign-ins)."""

    __tablename__ = "admin_audit_log"
    __table_args__ = (Index("ix_admin_audit_log_created_at", "created_at"),)

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_admins.id", ondelete="SET NULL"), nullable=True
    )
    actor_email: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)