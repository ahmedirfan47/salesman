"""The Stonic Console: site switches, analytics, businesses, people, system health and the audit log.

Same gate as the billing console (app.api.v1.platform): only the emails in
PLATFORM_ADMIN_EMAILS, and everyone else gets 404.
"""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.platform import require_platform_admin
from app.core.deps import CurrentUser, DBSession
from app.config import settings as app_settings
from app.modules.platform import console, site
from app.modules.platform.activity import audit
from app.schemas.console import AuditOut, PasswordIn, PersonUpdateIn, SiteSettingsIn, SuspendIn

router = APIRouter(prefix="/platform", tags=["console"], dependencies=[Depends(require_platform_admin)])


# ---- site switches ----
async def _settings_out(db) -> dict:
    updated_at, updated_by = await site.meta(db)
    return {
        "settings": await site.stored(db),
        "effective": await site.public(db),
        "updated_at": updated_at,
        "updated_by": updated_by,
        "admin_emails": sorted(app_settings.platform_admin_emails),
    }


@router.get("/settings")
async def get_settings(db: DBSession) -> dict:
    return await _settings_out(db)


@router.put("/settings")
async def save_settings(data: SiteSettingsIn, db: DBSession, user: CurrentUser) -> dict:
    try:
        changes = site.clean(data.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    before, after = await site.save(db, changes, user.email)
    diff = {k: {"from": before[k], "to": after[k]} for k in changes if before[k] != after[k]}
    if diff:
        audit(db, user, "site.settings", target_type="site", target_label="Site switches", detail=diff)
    await db.commit()
    return await _settings_out(db)


# ---- analytics ----
@router.get("/overview")
async def overview(db: DBSession, days: int = Query(30)) -> dict:
    return await console.overview(db, days)


# ---- businesses ----
@router.get("/businesses")
async def businesses(db: DBSession) -> list[dict]:
    return await console.businesses(db)


@router.get("/businesses/{tenant_id}")
async def business(tenant_id: uuid.UUID, db: DBSession) -> dict:
    return await console.business_detail(db, tenant_id)


@router.post("/businesses/{tenant_id}/suspend")
async def suspend(tenant_id: uuid.UUID, data: SuspendIn, db: DBSession, user: CurrentUser) -> dict:
    await console.suspend(db, user, tenant_id, data.reason)
    return await console.business_detail(db, tenant_id)


@router.post("/businesses/{tenant_id}/reactivate")
async def reactivate(tenant_id: uuid.UUID, db: DBSession, user: CurrentUser) -> dict:
    await console.reactivate(db, user, tenant_id)
    return await console.business_detail(db, tenant_id)


# ---- people ----
@router.get("/people")
async def people(
    db: DBSession,
    q: str | None = Query(None, max_length=100),
    tenant_id: uuid.UUID | None = None,
    role: str | None = Query(None, max_length=20),
    state: Literal["active", "inactive", "online"] | None = None,
) -> list[dict]:
    return await console.people(db, q=q, tenant_id=tenant_id, role=role, state=state)


@router.patch("/people/{user_id}")
async def update_person(user_id: uuid.UUID, data: PersonUpdateIn, db: DBSession, user: CurrentUser) -> dict:
    u = await console.update_person(db, user, user_id, is_active=data.is_active, role=data.role)
    return await console.person(db, u.id)


@router.post("/people/{user_id}/password")
async def set_password(user_id: uuid.UUID, data: PasswordIn, db: DBSession, user: CurrentUser) -> dict:
    u = await console.set_password(db, user, user_id, data.password)
    return await console.person(db, u.id)


@router.post("/people/{user_id}/sign-out")
async def sign_out(user_id: uuid.UUID, db: DBSession, user: CurrentUser) -> dict:
    u = await console.sign_out_everywhere(db, user, user_id)
    return await console.person(db, u.id)


# ---- system ----
@router.get("/system")
async def system(db: DBSession) -> dict:
    return await console.system(db)


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: uuid.UUID, db: DBSession, user: CurrentUser) -> dict:
    job = await console.retry_job(db, user, job_id)
    return {"id": job.id, "status": job.status}


@router.post("/jobs/{job_id}/discard")
async def discard_job(job_id: uuid.UUID, db: DBSession, user: CurrentUser) -> dict:
    job = await console.discard_job(db, user, job_id)
    return {"id": job.id, "status": job.status}


# ---- activity ----
@router.get("/sign-ins")
async def sign_ins(db: DBSession, failed: bool = False) -> list[dict]:
    return await console.sign_ins(db, failed_only=failed)


@router.get("/audit", response_model=list[AuditOut])
async def audit_log(db: DBSession) -> list[AuditOut]:
    return [AuditOut.model_validate(a) for a in await console.audit_log(db)]