from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware

from .db import SessionLocal, engine
from .models import Base
from .routers import auth, exports, inventory, operations, products, settings
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
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for stmt in MIGRATIONS:
            conn.execute(text(stmt))
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="StockSense API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth, settings, products, operations, inventory, exports):
    app.include_router(r.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"ok": True}
