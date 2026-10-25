import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import settings
from app.core.observability import install_observability
from app.db.session import SessionLocal, engine
from app.jobs.worker import run_forever


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    worker = None
    if settings.JOB_WORKER_ENABLED:
        worker = asyncio.create_task(run_forever(SessionLocal, stop, settings.JOB_POLL_SECONDS))
    try:
        yield
    finally:
        stop.set()
        if worker is not None:
            # give an in-flight job a moment to finish; it is retried if cut off
            with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(worker, timeout=10)
        await engine.dispose()


app = FastAPI(title=settings.PROJECT_NAME, version="0.1.0", lifespan=lifespan)

install_observability(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-request-id"],
)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["health"])
async def root() -> dict[str, str]:
    return {"service": settings.PROJECT_NAME, "status": "running"}