import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware

from .config import settings as app_settings
from .db import SessionLocal, engine
from .digest import run_digest_if_due
from .stock import utcnow
from .models import Base
from .routers import auth, exports, inventory, notifications, operations, parties, products, reports, settings
from .seed import seed


# create_all() only creates missing tables, so new columns on existing tables are added here.
MIGRATIONS = [
    "ALTER TABLE categories ADD COLUMN IF NOT EXISTS default_tax_id INTEGER REFERENCES taxes(id)",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS tax_id INTEGER REFERENCES taxes(id)",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS hsn_code VARCHAR(20)",
    "ALTER TABLE operation_lines ADD COLUMN IF NOT EXISTS unit_price DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE operation_lines ADD COLUMN IF NOT EXISTS tax_rate DOUBLE PRECISION DEFAULT 0",
    "ALTER TABLE operation_lines ADD COLUMN IF NOT EXISTS tax_name VARCHAR(60)",
    "ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE locations ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE operations ADD COLUMN IF NOT EXISTS picked_at TIMESTAMP",
    "ALTER TABLE operations ADD COLUMN IF NOT EXISTS packed_at TIMESTAMP",
    "ALTER TABLE operations ADD COLUMN IF NOT EXISTS party_id INTEGER REFERENCES parties(id)",
    "ALTER TABLE operations ADD COLUMN IF NOT EXISTS backorder_of_id INTEGER REFERENCES operations(id)",
    "ALTER TABLE operation_lines ADD COLUMN IF NOT EXISTS ordered_qty DOUBLE PRECISION",
    "ALTER TABLE operation_lines ADD COLUMN IF NOT EXISTS cost_price DOUBLE PRECISION",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS cost_price DOUBLE PRECISION NOT NULL DEFAULT 0",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS avg_cost DOUBLE PRECISION NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS low_stock_digest BOOLEAN NOT NULL DEFAULT FALSE",
]


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
            logging.getLogger("stocksense").exception("digest check failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for stmt in MIGRATIONS:
            conn.execute(text(stmt))
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
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth, settings, products, parties, operations, inventory, reports, exports, notifications):
    app.include_router(r.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"ok": True}
