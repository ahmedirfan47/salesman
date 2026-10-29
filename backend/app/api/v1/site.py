"""Public site status: whether sign-in and sign-up are open, and the banner. No sign-in needed."""
from fastapi import APIRouter

from app.core.deps import DBSession
from app.modules.platform import site

router = APIRouter(tags=["site"])


@router.get("/site")
async def site_status(db: DBSession) -> dict:
    return await site.public(db)