"""Postgres-backed job queue.

Why Postgres and not Redis: the app already has Postgres, Render's free plan
has no background-worker service, and SELECT ... FOR UPDATE SKIP LOCKED gives
safe concurrent claiming. If volume ever outgrows it, the enqueue/claim API
below is the only thing a Redis-based queue would need to replace.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.job import Job

# Job kinds (handlers live in app.jobs.handlers)
WHATSAPP_INBOUND_TEXT = "whatsapp.inbound_text"
WHATSAPP_INBOUND_AUDIO = "whatsapp.inbound_audio"
WHATSAPP_SEND_TEXT = "whatsapp.send_text"

# A job stuck in 'running' longer than this (e.g. the server restarted
# mid-job) is considered abandoned and is picked up again.
STALE_AFTER = timedelta(minutes=10)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def backoff_seconds(attempts: int) -> int:
    """15s, 30s, 60s, 120s ... capped at 10 minutes."""
    return min(15 * 2 ** max(attempts - 1, 0), 600)


async def enqueue(
    db: AsyncSession,
    kind: str,
    payload: dict,
    *,
    tenant_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
    max_attempts: int = 3,
    delay_seconds: int = 0,
    commit: bool = True,
) -> bool:
    """Add a job. Returns False if a job with the same dedupe_key already exists."""
    stmt = (
        insert(Job)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            kind=kind,
            payload=payload,
            status="queued",
            attempts=0,
            max_attempts=max_attempts,
            run_after=_now() + timedelta(seconds=delay_seconds),
            dedupe_key=dedupe_key,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(Job.id)
    )
    inserted = (await db.execute(stmt)).scalar_one_or_none()
    if commit:
        await db.commit()
    return inserted is not None


async def claim(db: AsyncSession) -> Job | None:
    """Atomically take the next due job (or an abandoned one) and mark it running."""
    now = _now()
    job = await db.scalar(
        select(Job)
        .where(
            or_(
                (Job.status == "queued") & (Job.run_after <= now),
                (Job.status == "running") & (Job.locked_at < now - STALE_AFTER),
            )
        )
        .order_by(Job.run_after)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        await db.commit()  # end the transaction (commit, unlike rollback, keeps loaded objects usable)
        return None
    job.status = "running"
    job.locked_at = now
    job.attempts += 1
    await db.commit()
    return job


async def mark_done(db: AsyncSession, job_id: uuid.UUID) -> None:
    job = await db.get(Job, job_id)
    if job is None:
        return
    job.status = "done"
    job.finished_at = _now()
    job.locked_at = None
    job.last_error = None
    await db.commit()


async def mark_failed(db: AsyncSession, job_id: uuid.UUID, error: str) -> bool:
    """Record a failure. Re-queues with backoff if attempts remain.

    Returns True when the job has now failed for good.
    """
    job = await db.get(Job, job_id)
    if job is None:
        return True
    job.last_error = error[:4000]
    job.locked_at = None
    final = job.attempts >= job.max_attempts
    if final:
        job.status = "failed"
        job.finished_at = _now()
    else:
        job.status = "queued"
        job.run_after = _now() + timedelta(seconds=backoff_seconds(job.attempts))
    await db.commit()
    return final