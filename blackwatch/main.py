"""BlackWatch application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import __version__, api, auth, noise, storage
from .config import settings
from .db import close_pool, init_pool
from .connectors import scheduler as connector_scheduler
from .modules import registry
from .notify import router as notify_router
from .notify import worker as notify_worker
from .rules import engine as rule_engine
from .ui import views as ui_views


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pool()
    registry.register_builtins()
    rule_engine.init_engine(settings.rules_dir)
    # Apply UI overrides (enabled + severity) on top of the YAML defaults.
    engine = rule_engine.get_engine()
    from .event import Severity as _Severity
    for rule_id, override in storage.get_rule_override_map().items():
        engine.set_enabled(rule_id, override["enabled"])
        sev_str = override.get("severity")
        if sev_str:
            try:
                engine.set_severity(rule_id, _Severity(sev_str))
            except ValueError:
                pass  # stale severity string in DB — fall back to YAML
    noise.refresh()
    notify_router.init_notifier(settings.notifications_file)
    notify_worker.start()
    connector_scheduler.start()
    # Seed the default admin/password if the auth_users table is empty.
    # No-op after the operator has created a real account.
    auth.seed_admin_if_empty()
    yield
    connector_scheduler.stop()
    notify_worker.stop()
    close_pool()


app = FastAPI(title="BlackWatch", version=__version__, lifespan=lifespan)


# ---- Auth middleware ------------------------------------------------------
# Every request that reaches the FastAPI app must carry a valid bw_session
# cookie, with a few explicit exemptions:
#
#   * /ingest, /api/ingest — machine ingestion, uses X-BLACKWATCH-TOKEN
#   * /auth/login, /auth/logout — cookie is *being* set/cleared here
#   * /                    — root redirect to /ui (harmless)
#   * /healthz             — uptime probe
#   * /docs, /openapi.json — FastAPI docs
#
# The rest — /events, /rules, /api/*, /ui/* — needs an authenticated
# session. The Next.js UI enforces its own redirect-to-login layer for the
# UI routes it serves (see blackwatch-ui/middleware.ts), so cookie
# validation here is the belt-and-suspenders backstop for anyone who tries
# to bypass the UI and hit the FastAPI port directly.
_PUBLIC_PATH_SET = {
    "/",
    "/healthz",
    "/ingest",
    "/api/ingest",
    "/auth/login",
    "/api/auth/login",
    "/auth/logout",
    "/api/auth/logout",
}
_PUBLIC_PATH_PREFIXES = ("/docs", "/openapi", "/redoc", "/static/")


def _needs_auth(path: str) -> bool:
    if path in _PUBLIC_PATH_SET:
        return False
    for prefix in _PUBLIC_PATH_PREFIXES:
        if path.startswith(prefix):
            return False
    return True


@app.middleware("http")
async def _auth_middleware(request: Request, call_next):
    if _needs_auth(request.url.path):
        sid = request.cookies.get(auth.COOKIE_NAME)
        result = auth.touch_session(sid) if sid else None
        if result is None:
            return JSONResponse(
                {"detail": "authentication required"}, status_code=401,
            )
        # Stash for downstream handlers that want the caller identity.
        request.state.user = result[0]
    return await call_next(request)


app.include_router(api.router)
# Mirror the JSON API under /api/* so the Next.js UI can call /api/events etc.
# without breaking existing agents that still POST to /ingest at the root.
app.include_router(api.router, prefix="/api")
app.include_router(ui_views.router)


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
