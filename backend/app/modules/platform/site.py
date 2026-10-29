"""Site switches: who may sign in or sign up, read-only mode and the banner.

Stored in one row (platform_settings, id = 1) and changed from the Stonic
Console. Read on every signed-in request, so the values are cached in each
process for a few seconds; a change reaches every server within that time.

Stonic admins (PLATFORM_ADMIN_EMAILS) are never locked out. If that list is
empty, the switches are ignored and the site stays open, so nobody can lock
everyone out by mistake.
"""
import time
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.db.models.platform import PlatformSettings

DEFAULTS: dict = {
    "sign_in_enabled": True,
    "sign_up_enabled": True,
    "read_only": False,
    "closed_message": "Salesman is getting ready for launch. Sign-in will open again soon.",
    "read_only_message": "Salesman is in read-only mode for maintenance. You can look at everything; changes are paused.",
    "banner_text": "",
    "banner_tone": "info",  # info | warning
}
TEXT_LIMITS = {"closed_message": 500, "read_only_message": 500, "banner_text": 300}
TONES = ("info", "warning")
SIGN_UP_CLOSED = "New sign-ups are closed right now. Contact Stonic to get an account."

_CACHE_SECONDS = 10.0
_cache: tuple[float, dict] | None = None


def invalidate() -> None:
    global _cache
    _cache = None


async def _row(db: AsyncSession) -> PlatformSettings:
    row = await db.get(PlatformSettings, 1)
    if row is None:
        row = PlatformSettings(id=1, data={})
        db.add(row)
        await db.flush()
    return row


def _merge(data: dict | None) -> dict:
    out = dict(DEFAULTS)
    for key, value in (data or {}).items():
        if key in DEFAULTS:
            out[key] = value
    return out


async def stored(db: AsyncSession) -> dict:
    """The switches as saved (what the console shows)."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_SECONDS:
        return dict(_cache[1])
    row = await db.get(PlatformSettings, 1)
    values = _merge(row.data if row else None)
    _cache = (now, values)
    return dict(values)


async def effective(db: AsyncSession) -> dict:
    """The switches as they apply right now (all open when no Stonic admin is configured)."""
    values = await stored(db)
    if not app_settings.platform_admin_emails:
        values.update(sign_in_enabled=True, sign_up_enabled=True, read_only=False)
    return values


async def public(db: AsyncSession) -> dict:
    """What the login, sign-up and plans pages may know (no secrets here)."""
    v = await effective(db)
    return {
        "sign_in_enabled": v["sign_in_enabled"],
        "sign_up_enabled": v["sign_up_enabled"] and v["sign_in_enabled"],
        "read_only": v["read_only"],
        "closed_message": v["closed_message"] if not v["sign_in_enabled"] else None,
        "read_only_message": v["read_only_message"] if v["read_only"] else None,
        "banner_text": v["banner_text"] or None,
        "banner_tone": v["banner_tone"],
    }


def clean(changes: dict) -> dict:
    """Validate a change from the console. Raises ValueError with a readable message."""
    out: dict = {}
    for key, value in changes.items():
        if key not in DEFAULTS:
            continue
        if isinstance(DEFAULTS[key], bool):
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be true or false")
            out[key] = value
        elif key == "banner_tone":
            if value not in TONES:
                raise ValueError("The banner tone must be info or warning")
            out[key] = value
        else:
            text = (value or "").strip()
            if len(text) > TEXT_LIMITS[key]:
                raise ValueError(f"Keep that message under {TEXT_LIMITS[key]} characters")
            if key in ("closed_message", "read_only_message") and not text:
                text = DEFAULTS[key]
            out[key] = text
    return out


async def save(db: AsyncSession, changes: dict, actor_email: str) -> tuple[dict, dict]:
    """Apply validated changes. Returns (before, after). Does not commit."""
    row = await _row(db)
    before = _merge(row.data)
    after = {**before, **changes}
    row.data = {k: after[k] for k in DEFAULTS}
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = actor_email
    invalidate()
    return before, after


async def meta(db: AsyncSession) -> tuple[datetime | None, str | None]:
    row = await db.get(PlatformSettings, 1)
    return (row.updated_at, row.updated_by) if row else (None, None)