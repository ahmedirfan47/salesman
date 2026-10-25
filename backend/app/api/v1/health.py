from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text

from app.core.deps import DBSession
from app.db.models.job import Job

router = APIRouter(tags=["health"])

# Queued jobs older than this mean the worker is not keeping up (or not running).
_BACKLOG_WARN_AFTER = timedelta(minutes=5)


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process is up. Cheap -- use for uptime pings."""
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(db: DBSession):
    """Readiness: the database answers and background jobs are flowing.

    Returns 503 if the database is unreachable, so Render (or an uptime
    monitor) can alert. A job backlog is reported but does not fail the check.
    """
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "error", "database": "unreachable"})

    now = datetime.now(timezone.utc)
    oldest_queued = await db.scalar(
        select(func.min(Job.run_after)).where(Job.status == "queued", Job.run_after <= now)
    )
    failed_24h = await db.scalar(
        select(func.count(Job.id)).where(Job.status == "failed", Job.finished_at >= now - timedelta(hours=24))
    )
    backlog_seconds = int((now - oldest_queued).total_seconds()) if oldest_queued else 0
    return {
        "status": "ok",
        "database": "ok",
        "jobs": {
            "oldest_waiting_seconds": backlog_seconds,
            "backlog": backlog_seconds > _BACKLOG_WARN_AFTER.total_seconds(),
            "failed_last_24h": int(failed_24h or 0),
        },
    }