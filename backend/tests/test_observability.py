"""Tests for structured logging and the global error handler."""
import json
import logging
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.observability import JsonFormatter, install_observability, request_id_ctx


@pytest.fixture
def app():
    a = FastAPI()

    @a.get("/ok")
    def ok():
        return {"status": "fine"}

    @a.get("/boom")
    def boom():
        raise ValueError("something broke internally")

    install_observability(a)
    return a


def test_successful_request_gets_request_id_header(app):
    client = TestClient(app)
    r = client.get("/ok")
    assert r.status_code == 200
    assert r.headers.get("x-request-id")


def test_incoming_request_id_is_preserved(app):
    """Lets a caller correlate logs across services."""
    client = TestClient(app)
    r = client.get("/ok", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"


def test_unhandled_error_returns_opaque_500_with_request_id(app):
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/boom")
    assert r.status_code == 500
    body = r.json()
    # must NOT leak the internal message to the client
    assert "something broke internally" not in json.dumps(body)
    assert body["detail"] == "An unexpected error occurred."
    assert body["request_id"]


def test_json_formatter_emits_parseable_line():
    request_id_ctx.set("rid-1")
    rec = logging.LogRecord("t", logging.INFO, "f", 1, "hello", None, None)
    rec.ctx_path = "/orders"
    parsed = json.loads(JsonFormatter().format(rec))
    assert parsed["msg"] == "hello"
    assert parsed["level"] == "INFO"
    assert parsed["request_id"] == "rid-1"
    assert parsed["path"] == "/orders"


def test_formatter_includes_exception_traceback():
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        rec = logging.LogRecord("t", logging.ERROR, "f", 1, "failed",
                                None, sys.exc_info())
    parsed = json.loads(JsonFormatter().format(rec))
    assert "kaboom" in parsed["exception"]