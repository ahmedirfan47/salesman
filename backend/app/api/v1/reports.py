from datetime import date, datetime, timezone

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.core.branches import BranchScope, get_branch
from app.core.deps import CurrentUser, DBSession
from app.db.models.tenant import Tenant
from app.modules.accounts import service as accounts
from app.modules.reports import accuracy, service
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
    scope: BranchScope,
    day: str | None = Query(None, description="YYYY-MM-DD; defaults to today (UTC)"),
) -> DailySummary:
    summary = await service.compute_daily_summary(db, user.tenant_id, _parse_day(day), scope)
    return DailySummary(**summary)


@router.get("/daily/pdf")
async def daily_pdf(
    db: DBSession,
    user: CurrentUser,
    scope: BranchScope,
    day: str | None = Query(None, description="YYYY-MM-DD; defaults to today (UTC)"),
) -> Response:
    d = _parse_day(day)
    summary = await service.compute_daily_summary(db, user.tenant_id, d, scope)
    tenant = await db.get(Tenant, user.tenant_id)
    business = tenant.name if tenant else "Salesman"
    if scope is not None:
        business = f"{business} - {(await get_branch(db, user.tenant_id, scope)).name}"
    pdf_bytes = service.render_pdf(business, summary)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="report-{d.isoformat()}.pdf"'},
    )

def _month(month: str | None, today: date) -> date:
    if not month:
        return today.replace(day=1)
    try:
        y, m = (int(x) for x in month.split("-")[:2])
        return date(y, m, 1)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(422, "month must be YYYY-MM") from None


@router.get("/accuracy")
async def accuracy_report(
    db: DBSession, user: CurrentUser, scope: BranchScope,
    month: str | None = Query(None, description="YYYY-MM; defaults to this month"),
) -> dict:
    """How often the AI's orders went through unchanged, per customer, for one month."""
    today = await accounts._today(db, user.tenant_id)
    return await accuracy.monthly(db, user.tenant_id, _month(month, today), scope)


@router.get("/accuracy.csv")
async def accuracy_csv(
    db: DBSession, user: CurrentUser, scope: BranchScope, month: str | None = Query(None),
) -> Response:
    today = await accounts._today(db, user.tenant_id)
    report = await accuracy.monthly(db, user.tenant_id, _month(month, today), scope)
    return Response(content=accuracy.to_csv(report), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="ai-accuracy-{report["month"]}.csv"'})
