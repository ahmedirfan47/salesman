import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select

from app.core.deps import CurrentUser, DBSession, require_role
from app.core.enums import UserRole
from app.db.models.print_job import PrintJob
from app.db.models.tenant import Tenant
from app.modules.printing import service
from app.schemas.printing import PrintJobOut, PrintJobStatusUpdate

router = APIRouter(prefix="/printing", tags=["printing"])


@router.get("/jobs", response_model=list[PrintJobOut])
async def list_jobs(
    db: DBSession,
    user: CurrentUser,
    job_status: str | None = Query(None, alias="status", description="queued|printing|done|failed"),
) -> list[PrintJobOut]:
    """List print jobs. The on-site print agent polls this with status=queued."""
    return await service.list_jobs(db, user.tenant_id, status=job_status)


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