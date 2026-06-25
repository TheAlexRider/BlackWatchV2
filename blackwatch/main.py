"""BlackWatch application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from . import __version__, api, noise, storage
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
    # Apply UI rule enable/disable overrides on top of the YAML defaults.
    engine = rule_engine.get_engine()
    for rule_id, enabled in storage.get_rule_overrides().items():
        engine.set_enabled(rule_id, enabled)
    noise.refresh()
    notify_router.init_notifier(settings.notifications_file)
    notify_worker.start()
    connector_scheduler.start()
    yield
    connector_scheduler.stop()
    notify_worker.stop()
    close_pool()


app = FastAPI(title="BlackWatch", version=__version__, lifespan=lifespan)
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
