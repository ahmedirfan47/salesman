"""Usage tracking for the Stonic Console: who is active, on which client, and sign-in attempts.

Kept cheap: a person's activity is written at most once per day per client
(remembered in memory), and `last_seen_at` at most every few minutes.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.platform import AdminAuditLog, LoginEvent, UserActivity
from app.db.models.user import User

CLIENT_HEADER = "x-client"
CLIENTS = ("web", "mobile", "api")
SEEN_EVERY = timedelta(minutes=5)
_MOBILE_HINTS = ("okhttp", "expo", "cfnetwork", "darwin", "dalvik", "reactnative", "react-native")

# (day, user_id, client) already recorded by this process
_recorded: set[tuple[date, uuid.UUID, str]] = set()
_recorded_day: date | None = None


def client_of(request: Request | None) -> str:
    """web (the dashboard), mobile (the app) or api (anything else)."""
    if request is None:
        return "api"
    told = (request.headers.get(CLIENT_HEADER) or "").strip().lower()
    if told in CLIENTS:
        return told
    agent = (request.headers.get("user-agent") or "").lower()
    if any(h in agent for h in _MOBILE_HINTS):
        return "mobile"
    if "mozilla" in agent:
        return "web"
    return "api"


def ip_of(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host[:64] if request.client else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def touch(db: AsyncSession, user: User, request: Request) -> None:
    """Record that this person used the product today, on this client. Commits only when it writes."""
    global _recorded_day
    now = _now()
    today = now.date()
    if _recorded_day != today:
        _recorded.clear()
        _recorded_day = today
    client = client_of(request)
    key = (today, user.id, client)
    wrote = False
    if key not in _recorded:
        await db.execute(
            insert(UserActivity)
            .values(day=today, user_id=user.id, client=client, tenant_id=user.tenant_id)
            .on_conflict_do_nothing()
        )
        _recorded.add(key)
        wrote = True
    if user.last_seen_at is None or now - user.last_seen_at > SEEN_EVERY:
        user.last_seen_at = now
        wrote = True
    if wrote:
        await db.commit()


def forget() -> None:
    """Clear the in-memory record (used by tests)."""
    _recorded.clear()


def login_event(db: AsyncSession, request: Request | None, email: str, *, user: User | None,
                success: bool, reason: str) -> None:
    """Add a sign-in attempt to the session. The caller commits."""
    db.add(LoginEvent(
        user_id=user.id if user else None, tenant_id=user.tenant_id if user else None,
        email=email.lower()[:255], client=client_of(request), success=success, reason=reason,
        ip=ip_of(request),
    ))


def audit(db: AsyncSession, actor: User, action: str, *, target_type: str | None = None,
          target_id=None, target_label: str | None = None, detail: dict | None = None) -> None:
    """Add a console action to the audit log. The caller commits."""
    db.add(AdminAuditLog(
        actor_id=actor.id, actor_email=actor.email, action=action, target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        target_label=(target_label or None) and target_label[:255], detail=detail or {},
    ))