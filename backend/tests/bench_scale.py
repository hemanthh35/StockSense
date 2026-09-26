"""Scale benchmark (not a test: pytest ignores it). Loads a large synthetic dataset into its own database and
times the endpoints that get slow as data grows.

    docker compose exec backend python tests/bench_scale.py            # build data (if needed) and time
    docker compose exec backend python tests/bench_scale.py --rebuild  # regenerate the dataset first
"""
import os
import random
import sys
import time
import uuid
from datetime import date, datetime, timedelta

import psycopg

BENCH_DB = "stocksense_bench"


def prepare() -> None:
    url = os.environ.get("DATABASE_URL", "postgresql+psycopg://stocksense:stocksense@localhost:5432/stocksense")
    base = url.rsplit("/", 1)[0]
    admin = base.replace("postgresql+psycopg", "postgresql") + "/postgres"
    with psycopg.connect(admin, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (BENCH_DB,)).fetchone():
            conn.execute(f"CREATE DATABASE {BENCH_DB}")
    os.environ["DATABASE_URL"] = f"{base}/{BENCH_DB}"
    os.environ["DIGEST_ENABLED"] = "false"
    os.environ["BREVO_API_KEY"] = ""


prepare()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, insert, select  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Base, Category, Location, Operation, OperationLine, Party, Product, StockQuant, Tax, Warehouse,
)

N_PRODUCTS, N_PARTIES, N_OPS, N_CATS = 8000, 1500, 30000, 40
random.seed(42)


def build(client: TestClient) -> None:
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Product)) >= N_PRODUCTS:
            return
        print(f"building dataset: {N_PRODUCTS} products, {N_OPS} documents ...", flush=True)
        t0 = time.time()
        tax = db.scalar(select(Tax).where(Tax.is_default.is_(True)))
        whs = [Warehouse(name=f"Bench WH {i}", short_code=f"B{i}") for i in range(3)]
        db.add_all(whs)
        db.flush()
        locs = []
        for w in whs:
            for j in range(4):
                l = Location(name=f"Bin{j}", short_code=f"Bin{j}", type="internal", warehouse_id=w.id)
                db.add(l)
                locs.append(l)
        db.flush()
        vendor = db.scalar(select(Location).where(Location.type == "vendor"))
        customer = db.scalar(select(Location).where(Location.type == "customer"))
        adjl = db.scalar(select(Location).where(Location.type == "adjustment"))
        db.execute(insert(Category), [{"name": f"Bench cat {i}"} for i in range(N_CATS)])
        db.commit()
        cat_ids = [c for (c,) in db.execute(select(Category.id).where(Category.name.like("Bench cat%")))]

        prods = []
        for i in range(N_PRODUCTS):
            price = round(random.uniform(50, 5000), 2)
            prods.append({"name": f"Bench product {i}", "sku": f"BP{i:06d}", "category_id": random.choice(cat_ids), "uom": "Unit",
                          "unit_cost": price, "cost_price": round(price * 0.7, 2), "avg_cost": round(price * 0.7, 2),
                          "reorder_min": random.choice([0, 0, 10, 20, 50]), "reorder_qty": random.choice([0, 25, 50, 100]),
                          "hsn_code": "9403", "tax_id": tax.id, "active": True})
        db.execute(insert(Product), prods)
        db.commit()
        pids = [p for (p,) in db.execute(select(Product.id).where(Product.sku.like("BP%")))]
        price = dict(db.execute(select(Product.id, Product.unit_cost).where(Product.sku.like("BP%"))).all())

        quants = []
        for pid in pids:
            for loc in random.sample(locs, random.choice([1, 1, 2])):
                quants.append({"product_id": pid, "location_id": loc.id, "quantity": random.choice([0, 3, 8, 15, 40, 120, 300])})
        db.execute(insert(StockQuant), quants)

        db.execute(insert(Party), [{"name": f"Bench party {i}", "kind": random.choice(["vendor", "customer", "both"]), "active": True} for i in range(N_PARTIES)])
        db.commit()
        party_ids = [p for (p,) in db.execute(select(Party.id).where(Party.name.like("Bench party%")))]

        ops, today = [], date.today()
        for i in range(N_OPS):
            t = random.choices(["IN", "OUT", "INT", "ADJ"], [30, 45, 15, 10])[0]
            w = random.choice(whs)
            wl = [l for l in locs if l.warehouse_id == w.id]
            status = random.choices(["draft", "waiting", "ready", "done", "cancelled"], [8, 6, 10, 70, 6])[0]
            if t == "ADJ":
                status = "done"
            src, dst = {"IN": (vendor, wl[0]), "OUT": (wl[0], customer), "INT": (wl[0], wl[1]), "ADJ": (adjl, wl[0])}[t]
            when = today + timedelta(days=random.randint(-60, 20))
            ops.append({"reference": f"{w.short_code}/{t}/{i:06d}", "type": t, "status": status, "contact": "Bench contact",
                        "schedule_date": when, "warehouse_id": w.id, "source_location_id": src.id, "dest_location_id": dst.id,
                        "party_id": random.choice(party_ids) if t in ("IN", "OUT") else None,
                        "done_at": datetime.combine(when, datetime.min.time()) if status == "done" else None})
        db.execute(insert(Operation), ops)
        db.commit()
        op_ids = [o for (o,) in db.execute(select(Operation.id).where(Operation.reference.like("B_/%")).order_by(Operation.id))]
        lines = []
        for oid in op_ids:
            for pid in random.sample(pids, random.randint(1, 4)):
                lines.append({"operation_id": oid, "product_id": pid, "quantity": random.randint(1, 30), "unit_price": price[pid],
                              "tax_rate": 18, "tax_name": "GST 18%", "cost_price": round(float(price[pid]) * 0.7, 2)})
        for k in range(0, len(lines), 5000):
            db.execute(insert(OperationLine), lines[k:k + 5000])
        db.commit()
        print(f"built in {time.time() - t0:.1f}s ({len(lines)} document lines)")


def timed(client: TestClient, label: str, path: str) -> None:
    best, size = None, 0
    for _ in range(2):
        t = time.perf_counter()
        r = client.get(path)
        dt = (time.perf_counter() - t) * 1000
        best = dt if best is None else min(best, dt)
        size = len(r.content)
        status = r.status_code
    print(f"  {label:<34} {best:>8.0f} ms   {size / 1024:>9.1f} KB   [{status}]")


def main() -> None:
    if "--rebuild" in sys.argv:
        Base.metadata.drop_all(engine)
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    with TestClient(app) as raw:
        r = raw.post("/api/auth/signup", json={"login_id": "bench_admin", "email": "bench@example.com", "password": "Str0ng!Passw", "confirm_password": "Str0ng!Passw"})
        token = r.json().get("token") or raw.post("/api/auth/login", json={"login_id": "bench_admin", "password": "Str0ng!Passw"}).json()["token"]
        raw.headers.update({"Authorization": f"Bearer {token}"})
        build(raw)
        if only:  # one endpoint, one run (used by the driver so a runaway request can be killed)
            t = time.perf_counter()
            resp = raw.get(only)
            print(f"{(time.perf_counter() - t) * 1000:.0f} ms  {len(resp.content) / 1024:.1f} KB  [{resp.status_code}]")
            return
        for path in ENDPOINTS:
            timed(raw, path, path)


ENDPOINTS = [
    "/api/products", "/api/stock", "/api/operations", "/api/moves", "/api/parties", "/api/dashboard",
    "/api/reports/valuation", "/api/reports/margin?days=365", "/api/reorder/suggestions",
    "/api/products?page=1&page_size=25", "/api/stock?page=1&page_size=25", "/api/operations?page=1&page_size=25",
    "/api/moves?page=1&page_size=25", "/api/parties?page=1&page_size=25", "/api/reports/valuation?page=1&page_size=25",
    "/api/reports/margin?days=365&page=1&page_size=25",
]


if __name__ == "__main__":
    main()
