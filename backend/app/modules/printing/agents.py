"""On-site print agents: a small program on a warehouse PC prints each new order slip.

The owner creates an agent for a branch on the dashboard and gets its key once
(stored hashed). The agent signs every request with that key, which can do
only four things, only for its branch: say it is alive, claim the next
slips, download a slip, and report printed or failed.

Claiming is atomic (FOR UPDATE SKIP LOCKED), so two agents on one branch
never print the same slip. A slip claimed but never reported (the PC was
switched off mid-print) is handed out again after RECLAIM_AFTER; after
MAX_ATTEMPTS it is marked failed for someone to look at.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.branches import get_branch
from app.db.models.branch import Branch
from app.db.models.print_agent import PrintAgent
from app.db.models.print_job import PrintJob

PREFIX = "spa_"
RECLAIM_AFTER = timedelta(minutes=5)
MAX_ATTEMPTS = 3
ONLINE_WITHIN = timedelta(minutes=2)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def to_out(agent: PrintAgent, branch_name: str | None = None) -> dict:
    return {
        "id": agent.id, "name": agent.name, "branch_id": agent.branch_id, "branch_name": branch_name,
        "key_prefix": agent.key_prefix, "printer": agent.printer, "version": agent.version,
        "last_seen_at": agent.last_seen_at, "revoked": agent.revoked_at is not None,
        "online": agent.revoked_at is None and agent.last_seen_at is not None and _now() - agent.last_seen_at < ONLINE_WITHIN,
        "created_at": agent.created_at,
    }


async def create(db: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID, name: str,
                 actor_id: uuid.UUID | None = None) -> tuple[dict, str]:
    branch = await get_branch(db, tenant_id, branch_id)
    key = PREFIX + secrets.token_urlsafe(32)
    agent = PrintAgent(tenant_id=tenant_id, branch_id=branch.id, name=name.strip()[:80] or "Warehouse printer",
                       key_prefix=key[:12], key_hash=_hash(key), created_by=actor_id)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return to_out(agent, branch.name), key


async def list_agents(db: AsyncSession, tenant_id: uuid.UUID, scope: uuid.UUID | None = None) -> list[dict]:
    q = select(PrintAgent, Branch.name).join(Branch, Branch.id == PrintAgent.branch_id).where(PrintAgent.tenant_id == tenant_id)
    if scope is not None:
        q = q.where(PrintAgent.branch_id == scope)
    return [to_out(a, name) for a, name in await db.execute(q.order_by(PrintAgent.revoked_at.nullsfirst(), PrintAgent.created_at))]


async def revoke(db: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    agent = await db.scalar(select(PrintAgent).where(PrintAgent.id == agent_id, PrintAgent.tenant_id == tenant_id))
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Print agent not found")
    agent.revoked_at = agent.revoked_at or _now()
    await db.execute(update(PrintJob).where(PrintJob.agent_id == agent.id, PrintJob.status == "printing")
                     .values(status="queued", agent_id=None, claimed_at=None))
    await db.commit()


async def authenticate(db: AsyncSession, key: str | None) -> PrintAgent:
    if not key or not key.startswith(PREFIX):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Print agent key missing")
    agent = await db.scalar(select(PrintAgent).where(PrintAgent.key_prefix == key[:12]))
    if agent is None or not secrets.compare_digest(agent.key_hash, _hash(key)) or agent.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This print agent key is not valid (revoked or mistyped)")
    agent.last_seen_at = _now()
    return agent


async def heartbeat(db: AsyncSession, agent: PrintAgent, printer: str | None, version: str | None) -> dict:
    from app.db.models.tenant import Tenant

    agent.printer = (printer or agent.printer or "")[:120] or None
    agent.version = (version or agent.version or "")[:32] or None
    branch = await db.get(Branch, agent.branch_id)
    tenant = await db.get(Tenant, agent.tenant_id)
    await db.commit()
    return {"agent": agent.name, "branch": branch.name if branch else None, "business": tenant.name if tenant else None,
            "poll_seconds": 5}


async def claim(db: AsyncSession, agent: PrintAgent, limit: int = 5) -> list[PrintJob]:
    now = _now()
    stale = and_(PrintJob.status == "printing", PrintJob.claimed_at < now - RECLAIM_AFTER)
    # slips claimed too often without a report: give up and show them as failed
    await db.execute(update(PrintJob).where(PrintJob.branch_id == agent.branch_id, stale, PrintJob.attempts >= MAX_ATTEMPTS)
                     .values(status="failed", error="Claimed by a print agent but never reported printed"))
    jobs = list(await db.scalars(
        select(PrintJob).where(
            PrintJob.tenant_id == agent.tenant_id, PrintJob.branch_id == agent.branch_id,
            or_(PrintJob.status == "queued", stale),
        ).order_by(PrintJob.created_at).limit(max(1, min(limit, 20))).with_for_update(skip_locked=True)
    ))
    for job in jobs:
        job.status, job.agent_id, job.claimed_at, job.attempts = "printing", agent.id, now, (job.attempts or 0) + 1
    await db.commit()
    return jobs


async def agent_job(db: AsyncSession, agent: PrintAgent, job_id: uuid.UUID) -> PrintJob:
    job = await db.scalar(select(PrintJob).where(PrintJob.id == job_id, PrintJob.tenant_id == agent.tenant_id,
                                                 PrintJob.branch_id == agent.branch_id))
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Print job not found")
    return job


async def report(db: AsyncSession, agent: PrintAgent, job_id: uuid.UUID, *, ok: bool, error: str | None = None) -> PrintJob:
    job = await agent_job(db, agent, job_id)
    if job.status == "done":
        return job          # reported twice (a retry after a timeout): nothing to do
    if ok:
        job.status, job.printed_at, job.error = "done", _now(), None
    elif (job.attempts or 0) < MAX_ATTEMPTS:
        job.status, job.error, job.agent_id, job.claimed_at = "queued", (error or "Printer error")[:500], None, None
    else:
        job.status, job.error = "failed", (error or "Printer error")[:500]
    await db.commit()
    await db.refresh(job)
    return job


async def retry(db: AsyncSession, tenant_id: uuid.UUID, job_id: uuid.UUID, scope: uuid.UUID | None = None) -> PrintJob:
    q = select(PrintJob).where(PrintJob.id == job_id, PrintJob.tenant_id == tenant_id)
    if scope is not None:
        q = q.where(PrintJob.branch_id == scope)
    job = await db.scalar(q)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Print job not found")
    job.status, job.error, job.agent_id, job.claimed_at, job.attempts = "queued", None, None, None, 0
    await db.commit()
    await db.refresh(job)
    return job
