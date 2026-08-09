"""RBAC + audit-log unit tests.

Runs without a live Postgres — we monkeypatch blackwatch.storage so the
FastAPI dependencies exercise the branching logic in isolation.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from blackwatch import auth, main


# --- require_role ----------------------------------------------------------

def _fake_request(user: str | None, role: str | None):
    class _S:
        pass
    class _R:
        state = _S()
    r = _R()
    if user is not None:
        r.state.user = user
    if role is not None:
        r.state.role = role
    return r


def test_require_role_admin_ok():
    dep = auth.require_role("admin")
    req = _fake_request("alice", "admin")
    user, role = dep(req)
    assert user == "alice" and role == "admin"


def test_require_role_viewer_blocked():
    dep = auth.require_role("admin")
    req = _fake_request("bob", "viewer")
    with pytest.raises(HTTPException) as exc:
        dep(req)
    assert exc.value.status_code == 403


def test_require_role_unauthenticated_401():
    dep = auth.require_role("admin")
    req = _fake_request(None, None)
    with pytest.raises(HTTPException) as exc:
        dep(req)
    assert exc.value.status_code == 401


# --- scrubbing -------------------------------------------------------------

def test_scrub_password_key():
    body = b'{"username":"a","password":"hunter2"}'
    out = main._scrub_body(body)
    assert "hunter2" not in out
    assert "***REDACTED***" in out


def test_scrub_aws_key():
    body = b'AKIAIOSFODNN7EXAMPLE is in here'
    out = main._scrub_body(body)
    assert "AKIAIOSFODNN7EXAMPLE" not in out


def test_scrub_jwt():
    body = b'{"authorization":"eyJhbGciOi.abcdef.ghijkl"}'
    out = main._scrub_body(body)
    assert "eyJhbGciOi" not in out
    assert "***REDACTED***" in out


# --- audit middleware integration -----------------------------------------

def test_audit_middleware_persists_scrubbed_body(monkeypatch):
    captured: dict = {}

    def fake_insert_audit(**kw):
        captured.update(kw)

    monkeypatch.setattr(main.storage, "insert_audit", fake_insert_audit)

    app = FastAPI()
    app.middleware("http")(main._audit_middleware)

    @app.post("/echo")
    async def echo(payload: dict):
        return {"ok": True}

    client = TestClient(app)
    r = client.post("/echo", json={"password": "hunter2", "keep": "v"})
    assert r.status_code == 200
    assert captured["method"] == "POST"
    assert captured["path"] == "/echo"
    assert captured["status"] == 200
    assert "hunter2" not in (captured["body_summary"] or "")
    assert "***REDACTED***" in (captured["body_summary"] or "")
