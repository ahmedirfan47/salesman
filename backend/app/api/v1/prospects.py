"""AI prospecting: the pipeline of shops to win (new ones and quiet customers).

Gated by MANAGE_PROSPECTS (owner, admin, salesman). Messages are drafted by
the AI from real prices and sent by the rep from his own WhatsApp, so
nothing is ever sent automatically from the business number.
"""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.config import settings
from app.core.branches import BranchScope
from app.core.deps import CurrentUser, DBSession, require_capability
from app.core.permissions import Capability
from app.db.models.tenant import Tenant
from app.modules.prospects import drafting, service
from app.modules.prospects.importer import ProspectFileError, parse_prospect_file
from app.schemas.prospect import (
    ContactedIn,
    ConvertIn,
    DraftIn,
    DraftOut,
    ImportResultOut,
    NoteIn,
    PlaceAdd,
    PlaceSearchOut,
    ProspectCreate,
    ProspectDetailOut,
    ProspectOut,
    ProspectSummaryOut,
    ProspectUpdate,
    WinbackRefreshOut,
)

router = APIRouter(
    prefix="/prospects",
    tags=["prospects"],
    dependencies=[Depends(require_capability(Capability.MANAGE_PROSPECTS))],
)

_MAX_UPLOAD_BYTES = 5 * 1024 * 1024


# Static paths first: "/{prospect_id}" would otherwise try to read "summary" as an id.

@router.get("/summary", response_model=ProspectSummaryOut)
async def summary(db: DBSession, user: CurrentUser, scope: BranchScope) -> ProspectSummaryOut:
    return ProspectSummaryOut.model_validate(await service.summary(db, user.tenant_id, scope))


@router.get("", response_model=list[ProspectOut])
async def list_prospects(
    db: DBSession,
    user: CurrentUser, scope: BranchScope,
    kind: Literal["new", "winback"] | None = None,
    status_: str | None = Query(None, alias="status", pattern="^(open|new|contacted|interested|won|lost)$"),
    mine: bool = False,
    q: str | None = Query(None, max_length=100),
) -> list[ProspectOut]:
    rows = await service.list_prospects(
        db, user.tenant_id, kind=kind, status_=status_, assigned_to=user.id if mine else None, q=q, scope=scope,
    )
    return [ProspectOut.model_validate(r) for r in rows]


@router.post("", response_model=ProspectDetailOut, status_code=status.HTTP_201_CREATED)
async def create_prospect(data: ProspectCreate, db: DBSession, user: CurrentUser, scope: BranchScope) -> ProspectDetailOut:
    return ProspectDetailOut.model_validate(
        await service.create_prospect(db, user.tenant_id, user, data.model_dump(), scope=scope)
    )


@router.post("/import", response_model=ImportResultOut)
async def import_prospects(db: DBSession, user: CurrentUser, scope: BranchScope, file: UploadFile = File(...)) -> ImportResultOut:
    """Upload an .xlsx or .csv list of shops. Only a name column is required."""
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File exceeds the 5 MB limit.")
    try:
        rows, problems = parse_prospect_file(
            content, file.filename or "upload.xlsx", settings.PROSPECT_DEFAULT_COUNTRY_CODE
        )
    except ProspectFileError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return ImportResultOut.model_validate(await service.import_rows(db, user.tenant_id, user, rows, problems, scope))


@router.get("/places/search", response_model=PlaceSearchOut)
async def search_places(
    db: DBSession,
    user: CurrentUser, scope: BranchScope,
    q: str = Query(..., min_length=2, max_length=200, description="e.g. 'grocery store in Al Olaya, Riyadh'"),
    language: Literal["en", "ar"] = "en",
    page_token: str | None = Query(None, max_length=2000),
) -> PlaceSearchOut:
    return PlaceSearchOut.model_validate(
        await service.search_google(db, user.tenant_id, q, language, page_token)
    )


@router.post("/places", response_model=ProspectDetailOut, status_code=status.HTTP_201_CREATED)
async def add_place(data: PlaceAdd, db: DBSession, user: CurrentUser, scope: BranchScope) -> ProspectDetailOut:
    return ProspectDetailOut.model_validate(
        await service.add_from_google(db, user.tenant_id, user, data.model_dump(), scope)
    )


@router.post("/winback/refresh", response_model=WinbackRefreshOut)
async def refresh_winbacks(db: DBSession, user: CurrentUser, scope: BranchScope) -> WinbackRefreshOut:
    """Add customers who are ordering far less often than usual; close ones who ordered again."""
    return WinbackRefreshOut.model_validate(await service.refresh_winbacks(db, user.tenant_id, user, scope))


@router.get("/{prospect_id}", response_model=ProspectDetailOut)
async def get_prospect(prospect_id: uuid.UUID, db: DBSession, user: CurrentUser, scope: BranchScope) -> ProspectDetailOut:
    return ProspectDetailOut.model_validate(await service.detail(db, user.tenant_id, prospect_id, scope))


@router.patch("/{prospect_id}", response_model=ProspectDetailOut)
async def update_prospect(
    prospect_id: uuid.UUID, data: ProspectUpdate, db: DBSession, user: CurrentUser, scope: BranchScope
) -> ProspectDetailOut:
    return ProspectDetailOut.model_validate(
        await service.update_prospect(
            db, user.tenant_id, prospect_id, user, data.model_dump(exclude_unset=True), scope
        )
    )


@router.post("/{prospect_id}/draft", response_model=DraftOut)
async def draft(prospect_id: uuid.UUID, data: DraftIn, db: DBSession, user: CurrentUser, scope: BranchScope) -> DraftOut:
    """AI-written WhatsApp message using only real prices. Not sent, not saved."""
    p = await service.get_prospect(db, user.tenant_id, prospect_id, scope)
    tenant = await db.get(Tenant, user.tenant_id)
    facts = await drafting.build_facts(
        db, p, business=tenant.name, rep=user.full_name, language=data.language
    )
    message, source = await drafting.draft_message(facts)
    return DraftOut(message=message, language=data.language, source=source)


@router.post("/{prospect_id}/contacted", response_model=ProspectDetailOut)
async def contacted(
    prospect_id: uuid.UUID, data: ContactedIn, db: DBSession, user: CurrentUser, scope: BranchScope
) -> ProspectDetailOut:
    """Record that the rep opened WhatsApp with this message."""
    return ProspectDetailOut.model_validate(
        await service.mark_contacted(db, user.tenant_id, prospect_id, user, data.message, scope)
    )


@router.post("/{prospect_id}/notes", response_model=ProspectDetailOut)
async def add_note(prospect_id: uuid.UUID, data: NoteIn, db: DBSession, user: CurrentUser, scope: BranchScope) -> ProspectDetailOut:
    return ProspectDetailOut.model_validate(await service.add_note(db, user.tenant_id, prospect_id, user, data.text, scope))


@router.post("/{prospect_id}/convert", response_model=ProspectDetailOut)
async def convert(prospect_id: uuid.UUID, data: ConvertIn, db: DBSession, user: CurrentUser, scope: BranchScope) -> ProspectDetailOut:
    """Close as won. A new shop is added as a customer (or linked if it already is one)."""
    return ProspectDetailOut.model_validate(
        await service.convert(db, user.tenant_id, prospect_id, user, data.zone_id, scope)
    )