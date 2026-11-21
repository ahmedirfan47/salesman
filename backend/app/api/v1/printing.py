import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select

from app.core.branches import BranchScope
from app.core.deps import CurrentUser, DBSession, require_capability, require_role
from app.core.enums import UserRole
from app.core.permissions import Capability
from app.db.models.print_job import PrintJob
from app.db.models.tenant import Tenant
from app.modules.printing import agents, service
from app.schemas.printing import (
    AgentReportIn,
    HeartbeatIn,
    PrintAgentCreated,
    PrintAgentIn,
    PrintAgentOut,
    PrintJobOut,
    PrintJobStatusUpdate,
)

router = APIRouter(prefix="/printing", tags=["printing"])


@router.get("/jobs", response_model=list[PrintJobOut])
async def list_jobs(
    db: DBSession,
    user: CurrentUser,
    scope: BranchScope,
    job_status: str | None = Query(None, alias="status", description="queued|printing|done|failed"),
) -> list[PrintJobOut]:
    """List print jobs. The on-site print agent polls this with status=queued."""
    return await service.list_jobs(db, user.tenant_id, status=job_status, scope=scope)


@router.post("/jobs/{job_id}/status", response_model=PrintJobOut)
async def update_job_status(
    job_id: uuid.UUID, data: PrintJobStatusUpdate, db: DBSession, user: CurrentUser
) -> PrintJobOut:
    """The print agent reports a job as printing/done/failed."""
    return await service.mark_status(
        db, user.tenant_id, job_id, status=data.status, error=data.error
    )


@router.get("/jobs/{job_id}/slip.pdf")
async def job_slip_pdf(job_id: uuid.UUID, db: DBSession, user: CurrentUser) -> Response:
    """Render the printable slip PDF for a job (agent fetches this to print)."""
    job = await db.scalar(
        select(PrintJob).where(PrintJob.id == job_id, PrintJob.tenant_id == user.tenant_id)
    )
    if not job:
        raise HTTPException(404, "Print job not found")
    tenant = await db.get(Tenant, user.tenant_id)
    business = tenant.name if tenant else "Salesman"
    pdf = service.render_slip_pdf(business, job.payload)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="slip-{job.payload.get("order_number","order")}.pdf"'},
    )


# ---- print agents: managed by the owner ------------------------------------------------------

_admin = Depends(require_role(UserRole.ADMIN))


@router.get("/agents", response_model=list[PrintAgentOut], dependencies=[Depends(require_capability(Capability.VIEW_PRINTING))])
async def list_agents(db: DBSession, user: CurrentUser, scope: BranchScope):
    return await agents.list_agents(db, user.tenant_id, scope)


@router.post("/agents", response_model=PrintAgentCreated, dependencies=[_admin])
async def create_agent(data: PrintAgentIn, db: DBSession, user: CurrentUser):
    """Create a print agent for a branch. The key is shown only in this answer."""
    agent, key = await agents.create(db, user.tenant_id, data.branch_id, data.name, user.id)
    return {"agent": agent, "key": key}


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_admin])
async def revoke_agent(agent_id: uuid.UUID, db: DBSession, user: CurrentUser) -> None:
    await agents.revoke(db, user.tenant_id, agent_id)


@router.post("/jobs/{job_id}/retry", response_model=PrintJobOut,
             dependencies=[Depends(require_capability(Capability.VIEW_PRINTING))])
async def retry_job(job_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope):
    """Print a slip again (after fixing the printer, or for a lost copy)."""
    return await agents.retry(db, user.tenant_id, job_id, scope)


# ---- print agents: called by the agent on the warehouse PC, with its own key -----------------

async def _agent(db: DBSession, x_print_agent_key: str | None = Header(default=None)):
    return await agents.authenticate(db, x_print_agent_key)


@router.post("/agent/heartbeat")
async def agent_heartbeat(data: HeartbeatIn, db: DBSession, agent=Depends(_agent)) -> dict:
    return await agents.heartbeat(db, agent, data.printer, data.version)


@router.post("/agent/claim", response_model=list[PrintJobOut])
async def agent_claim(db: DBSession, agent=Depends(_agent), limit: int = Query(5, ge=1, le=20)):
    """The next slips to print for this agent's branch, now marked as printing."""
    return await agents.claim(db, agent, limit)


@router.get("/agent/jobs/{job_id}/slip.pdf")
async def agent_slip(job_id: uuid.UUID, db: DBSession, agent=Depends(_agent)) -> Response:
    job = await agents.agent_job(db, agent, job_id)
    tenant = await db.get(Tenant, agent.tenant_id)
    pdf = service.render_slip_pdf(tenant.name if tenant else "Salesman", job.payload)
    await db.commit()
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="slip-{job.payload.get("order_number", "order")}.pdf"'})


@router.post("/agent/jobs/{job_id}/report", response_model=PrintJobOut)
async def agent_report(job_id: uuid.UUID, data: AgentReportIn, db: DBSession, agent=Depends(_agent)):
    """Printed (ok=true) or not (ok=false with the error). A failed slip is tried again up to 3 times."""
    return await agents.report(db, agent, job_id, ok=data.ok, error=data.error)
