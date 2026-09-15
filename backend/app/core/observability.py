"""Structured logging, request tracing, and a global error handler.

Deliberately dependency-free: JSON logs to stdout are enough to get real
visibility today, and Render/most hosts ingest stdout automatically. If you
later add Sentry, `install_observability` is the single place to wire it.
"""
import json
import logging
import sys
import time
import traceback
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Correlates every log line emitted while handling one request.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    """One JSON object per line -- greppable, and parseable by log tooling."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_ctx.get(),
        }
        # Anything passed via logger.info("x", extra={"ctx_foo": 1})
        for key, value in getattr(record, "__dict__", {}).items():
            if key.startswith("ctx_"):
                payload[key[4:]] = value
        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn's own access log duplicates our middleware log -- quiet it.
    logging.getLogger("uvicorn.access").disabled = True


logger = logging.getLogger("salesman")


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, times the request, logs the outcome.

    Slow requests are logged at WARNING so they stand out -- useful while
    the AI agent still runs inline on the request thread.
    """

    def __init__(self, app, slow_request_ms: int = 2000):
        super().__init__(app)
        self.slow_request_ms = slow_request_ms

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request_id_ctx.set(rid)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "request failed",
                extra={
                    "ctx_method": request.method,
                    "ctx_path": request.url.path,
                    "ctx_duration_ms": round(duration_ms, 1),
                },
            )
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        level = logging.WARNING if duration_ms > self.slow_request_ms else logging.INFO
        logger.log(
            level,
            "request",
            extra={
                "ctx_method": request.method,
                "ctx_path": request.url.path,
                "ctx_status": response.status_code,
                "ctx_duration_ms": round(duration_ms, 1),
                "ctx_slow": duration_ms > self.slow_request_ms,
            },
        )
        response.headers["x-request-id"] = rid
        return response


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catches anything that escaped a route.

    Logs the full traceback server-side but returns an opaque message plus the
    request id -- so a user can quote the id to support without us leaking
    internals to the client.
    """
    logger.exception(
        "unhandled exception",
        extra={"ctx_method": request.method, "ctx_path": request.url.path},
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected error occurred.",
            "request_id": request_id_ctx.get(),
        },
    )


def install_observability(app: FastAPI, *, log_level: str = "INFO") -> None:
    """Call once from app startup."""
    configure_logging(log_level)
    app.add_middleware(RequestLogMiddleware)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    # TODO(sentry): if/when you add Sentry, initialise it here -- everything
    # else (request ids, structured logs) already lines up with it.