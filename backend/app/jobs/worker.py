"""Job worker.

Runs inside the API process by default (started from app.main's lifespan), so
no extra Render service is needed. It can also run on its own:

    python -m app.jobs.worker

Several workers (in-process or standalone) can run at once; claiming uses
SKIP LOCKED so a job is never processed twice concurrently.
"""
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs import queue

logger = logging.getLogger("salesman.jobs")

Handler = Callable[[AsyncSession, dict], Awaitable[None]]
HANDLERS: dict[str, Handler] = {}

# Housekeeping that runs alongside the queue (first run right after start-up).
SWEEP_EVERY_SECONDS = 3600


def handler(kind: str) -> Callable[[Handler], Handler]:
    """Register a coroutine as the handler for one job kind."""

    def register(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return register


def _load_handlers() -> None:
    # Imported here (not at module top) so app.jobs.queue stays importable
    # from the code that enqueues jobs without circular imports.
    import app.jobs.handlers  # noqa: F401


async def run_once(session_factory: async_sessionmaker) -> bool:
    """Process at most one job. Returns True if a job was found."""
    async with session_factory() as db:
        job = await queue.claim(db)
    if job is None:
        return False

    log_ctx = {"ctx_job_id": str(job.id), "ctx_job_kind": job.kind, "ctx_attempt": job.attempts}
    fn = HANDLERS.get(job.kind)
    try:
        if fn is None:
            raise RuntimeError(f"No handler registered for job kind '{job.kind}'")
        async with session_factory() as db:
            await fn(db, job.payload)
    except Exception as exc:  # noqa: BLE001 -- every failure is recorded, never lost
        async with session_factory() as db:
            final = await queue.mark_failed(db, job.id, f"{type(exc).__name__}: {exc}")
        if final:
            logger.exception("job failed permanently", extra=log_ctx)
        else:
            logger.warning("job failed, will retry", extra={**log_ctx, "ctx_error": str(exc)})
        return True

    async with session_factory() as db:
        await queue.mark_done(db, job.id)
    logger.info("job done", extra=log_ctx)
    return True


async def sweep(session_factory: async_sessionmaker) -> None:
    """Periodic work: issue monthly invoices that have come due."""
    from app.modules.billing.service import issue_due_invoices

    async with session_factory() as db:
        issued = await issue_due_invoices(db)
    if issued:
        logger.info("monthly invoices issued", extra={"ctx_count": issued})


async def run_forever(
    session_factory: async_sessionmaker,
    stop: asyncio.Event,
    poll_seconds: float = 1.0,
) -> None:
    _load_handlers()
    logger.info("job worker started")
    next_sweep = time.monotonic()
    while not stop.is_set():
        if time.monotonic() >= next_sweep:
            next_sweep = time.monotonic() + SWEEP_EVERY_SECONDS
            try:
                await sweep(session_factory)
            except Exception:  # noqa: BLE001 -- retried at the next sweep
                logger.exception("periodic sweep failed")
        try:
            worked = await run_once(session_factory)
        except Exception:  # noqa: BLE001 -- e.g. the database is briefly unreachable
            logger.exception("job worker loop error")
            worked = False
        if not worked:
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
            except asyncio.TimeoutError:
                pass
    logger.info("job worker stopped")


def main() -> None:
    from app.config import settings
    from app.core.observability import configure_logging, init_sentry
    from app.db.session import SessionLocal

    configure_logging()
    init_sentry()
    asyncio.run(run_forever(SessionLocal, asyncio.Event(), settings.JOB_POLL_SECONDS))


if __name__ == "__main__":
    main()