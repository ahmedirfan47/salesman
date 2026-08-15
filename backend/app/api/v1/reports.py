from datetime import date, datetime, timezone

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.core.deps import CurrentUser, DBSession
from app.db.models.tenant import Tenant
from app.modules.reports import service
from app.schemas.report import DailySummary

router = APIRouter(prefix="/reports", tags=["reports"])


def _parse_day(day: str | None) -> date:
    if not day:
        return datetime.now(timezone.utc).date()
    return date.fromisoformat(day)


@router.get("/daily/summary", response_model=DailySummary)
async def daily_summary(
    db: DBSession,
    user: CurrentUser,
    day: str | None = Query(None, description="YYYY-MM-DD; defaults to today (UTC)"),
) -> DailySummary:
    summary = await service.compute_daily_summary(db, user.tenant_id, _parse_day(day))
    return DailySummary(**summary)


@router.get("/daily/pdf")
async def daily_pdf(
    db: DBSession,
    user: CurrentUser,
    day: str | None = Query(None, description="YYYY-MM-DD; defaults to today (UTC)"),
) -> Response:
    d = _parse_day(day)
    summary = await service.compute_daily_summary(db, user.tenant_id, d)
    tenant = await db.get(Tenant, user.tenant_id)
    business = tenant.name if tenant else "Salesman"
    pdf_bytes = service.render_pdf(business, summary)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="report-{d.isoformat()}.pdf"'},
    )