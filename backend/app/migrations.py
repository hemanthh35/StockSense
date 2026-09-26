"""Schema upgrades for databases created by an older version. Every step is idempotent, so it is safe to run on
each start: `create_all` builds missing tables and these steps bring existing ones up to date."""
import logging
import re

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

log = logging.getLogger("stocksense.migrations")

COLUMNS = [
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
    # roles: everyone who existed before roles keeps full access; people who sign up from now on start as staff
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(10) NOT NULL DEFAULT 'admin'",
    "ALTER TABLE users ALTER COLUMN role SET DEFAULT 'staff'",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE",
    # optimistic locking
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE parties ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE operations ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS barcode VARCHAR(64)",
    "ALTER TABLE operation_lines ADD COLUMN IF NOT EXISTS lot_no VARCHAR(40)",
    "ALTER TABLE operation_lines ADD COLUMN IF NOT EXISTS expiry_date DATE",
]
MIGRATIONS = COLUMNS  # kept for older callers

# floating-point columns that became exact decimals
NUMERIC_COLUMNS = {
    "products": {"unit_cost": "NUMERIC(14,4)", "cost_price": "NUMERIC(14,4)", "avg_cost": "NUMERIC(14,4)",
                 "reorder_min": "NUMERIC(14,3)", "reorder_qty": "NUMERIC(14,3)"},
    "stock_quants": {"quantity": "NUMERIC(14,3)"},
    "operation_lines": {"quantity": "NUMERIC(14,3)", "ordered_qty": "NUMERIC(14,3)", "unit_price": "NUMERIC(14,4)",
                        "cost_price": "NUMERIC(14,4)", "tax_rate": "NUMERIC(7,3)"},
    "taxes": {"rate": "NUMERIC(7,3)"},
}

# names match what SQLAlchemy generates from `index=True`, so fresh and upgraded databases end up identical
INDEXES = [
    ("ix_operations_warehouse_id", "operations", "warehouse_id"),
    ("ix_operations_party_id", "operations", "party_id"),
    ("ix_operations_schedule_date", "operations", "schedule_date"),
    ("ix_operations_source_location_id", "operations", "source_location_id"),
    ("ix_operations_dest_location_id", "operations", "dest_location_id"),
    ("ix_operations_backorder_of_id", "operations", "backorder_of_id"),
    ("ix_operations_type_status", "operations", "type, status"),
    ("ix_operation_lines_operation_id", "operation_lines", "operation_id"),
    ("ix_operation_lines_product_id", "operation_lines", "product_id"),
    ("ix_stock_quants_location_id", "stock_quants", "location_id"),
    ("ix_products_category_id", "products", "category_id"),
    ("ix_products_active", "products", "active"),
    ("ix_products_barcode", "products", "barcode"),
    ("ix_locations_warehouse_id", "locations", "warehouse_id"),
]


def _convert_numeric(conn: Connection) -> None:
    for table, cols in NUMERIC_COLUMNS.items():
        for col, typ in cols.items():
            current = conn.execute(
                text("SELECT data_type FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
                {"t": table, "c": col},
            ).scalar()
            if current == "double precision":
                scale = int(re.search(r",(\d+)\)", typ).group(1))
                conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE {typ} USING ROUND({col}::numeric, {scale})"))
                log.info("converted %s.%s to %s", table, col, typ)


def _add_indexes(conn: Connection) -> None:
    for name, table, cols in INDEXES:
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"))


def _add_stock_check(conn: Connection) -> None:
    """Stock can never go below zero. If old data already breaks that, skip the constraint and say so."""
    if conn.execute(text("SELECT 1 FROM pg_constraint WHERE conname = 'ck_stock_quants_nonnegative'")).first():
        return
    try:
        with conn.begin_nested():
            conn.execute(text("ALTER TABLE stock_quants ADD CONSTRAINT ck_stock_quants_nonnegative CHECK (quantity >= 0)"))
    except Exception:
        log.warning("Some stock rows are negative, so the non-negative check was not added. Fix them and restart.")


def run_migrations(engine: Engine) -> None:
    with engine.begin() as conn:
        for stmt in COLUMNS:
            conn.execute(text(stmt))
        _convert_numeric(conn)
        _add_indexes(conn)
        _add_stock_check(conn)
