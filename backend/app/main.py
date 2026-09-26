import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from . import audit  # noqa: F401  (registers the audit_log table with the metadata)
from .assistant import service as _assistant_service  # noqa: F401  (registers the assistant_actions table)
from .config import settings as app_settings
from .db import SessionLocal, engine
from .digest import run_digest_if_due
from .migrations import MIGRATIONS, run_migrations  # noqa: F401  (MIGRATIONS re-exported for older callers)
from .models import Base
from .routers import assistant, auth, exports, inventory, notifications, operations, parties, products, reports, settings, users
from .seed import seed
from .stock import utcnow

log = logging.getLogger("stocksense")


def _digest_tick() -> None:
    with SessionLocal() as db:
        run_digest_if_due(db, utcnow(), app_settings.digest_hour_utc)


async def _digest_loop() -> None:
    """Wake up every 15 minutes; the digest itself is sent at most once a day."""
    while True:
        await asyncio.sleep(900)
        try:
            await asyncio.to_thread(_digest_tick)
        except Exception:  # never let a failed email kill the loop
            log.exception("digest check failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    problem = app_settings.check_secure()
    if problem:
        if app_settings.production:
            raise RuntimeError(f"Refusing to start in production: {problem}")
        log.warning("Insecure configuration (fine for local development only): %s", problem)
    Base.metadata.create_all(engine)
    run_migrations(engine)
    with SessionLocal() as db:
        seed(db)
    task = asyncio.create_task(_digest_loop()) if app_settings.digest_enabled else None
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="StockSense API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (assistant, auth, users, settings, products, parties, operations, inventory, reports, exports, notifications):
    app.include_router(r.router, prefix="/api")


@app.get("/api/health")
def health():
    """Liveness plus a real database round-trip, so an orchestrator can tell 'up' from 'up but broken'."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "database": "up"}
    except Exception:
        from fastapi.responses import JSONResponse

        return JSONResponse({"ok": False, "database": "down"}, status_code=503)
