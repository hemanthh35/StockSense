"""Demo dataset for presentations.

    docker compose exec backend python -m app.demo            # add the demo data (skips if already present)
    docker compose exec backend python -m app.demo --reset    # wipe products/documents/warehouses and rebuild

Builds two warehouses, five categories with default taxes, 18 products with HSN codes and reorder rules, and
a realistic mix of receipts, deliveries, transfers and adjustments in every status. See DEMO.md for a
click-through script. Users and taxes are never deleted.
"""
import argparse
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select

from . import pricing, stock
from .db import SessionLocal, engine
from .main import MIGRATIONS
from .models import (
    Base, Category, Location, Operation, OperationLine, Product, Sequence, StockQuant, Tax, User, Warehouse,
)
from .routers.operations import LineIn, _make_lines, _resolve_locations
from .security import hash_secret
from .seed import seed_taxes, seed_virtual_locations

# Demo account. Change it if this is ever exposed beyond a local demo.
DEMO_LOGIN = "demo_admin"
DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "Demo@12345"

CATEGORIES = {"Furniture": 18, "Electronics": 18, "Stationery": 12, "Packaging": 12, "Pantry": 5}

# sku, name, category, price, hsn, reorder_min, reorder_qty, opening stock, location key
PRODUCTS = [
    ("CHAIR001", "Office Chair", "Furniture", 4200, "9401", 8, 20, 30, "WH/S1"),
    ("DESK002", "Standing Desk", "Furniture", 18500, "9403", 5, 10, 3, "WH/S1"),
    ("SHELF001", "Bookshelf", "Furniture", 6400, "9403", 6, 12, 14, "WH/S1"),
    ("TABLE002", "Conference Table", "Furniture", 24000, "9403", 2, 4, 0, "WH/S1"),
    ("MON024", 'Monitor 24"', "Electronics", 9800, "8528", 10, 20, 12, "WH/S2"),
    ("KEYB001", "Keyboard", "Electronics", 1500, "8471", 15, 30, 4, "WH/S2"),
    ("MOUSE01", "Wireless Mouse", "Electronics", 899, "8471", 20, 40, 55, "WH/S1"),
    ("HUB001", "USB-C Hub", "Electronics", 2300, "8536", 12, 24, 9, "WH/S2"),
    ("CAM001", "Webcam HD", "Electronics", 3200, "8525", 8, 16, 20, "ND/A"),
    ("PAPER01", "A4 Paper Ream", "Stationery", 320, "4802", 40, 100, 150, "WH/S1"),
    ("PEN001", "Ballpoint Pens (box)", "Stationery", 180, "9608", 25, 50, 90, "WH/S1"),
    ("STICKY1", "Sticky Notes", "Stationery", 90, "4820", 30, 60, 18, "WH/S1"),
    ("MARK01", "Whiteboard Marker", "Stationery", 60, "9609", 40, 100, 200, "ND/B"),
    ("BOXM01", "Cardboard Box M", "Packaging", 45, "4819", 100, 300, 320, "WH/S1"),
    ("BUBBLE1", "Bubble Wrap Roll", "Packaging", 650, "3923", 10, 20, 35, "WH/S1"),
    ("TAPE001", "Packing Tape", "Packaging", 70, "3919", 50, 200, 260, "WH/S1"),
    ("TEA100", "Green Tea 100g", "Pantry", 240, "0902", 20, 40, 60, "WH/S2"),
    ("COF250", "Coffee Beans 250g", "Pantry", 480, "0901", 15, 30, 45, "WH/S2"),
]


def reset(db) -> None:
    for model in (OperationLine, Operation, StockQuant, Sequence, Product, Category):
        db.execute(delete(model))
    db.execute(delete(Location).where(Location.warehouse_id.isnot(None)))
    db.execute(delete(Warehouse))
    db.commit()


def build(db) -> dict:
    seed_virtual_locations(db)
    seed_taxes(db)

    user = db.scalar(select(User).where(User.login_id == DEMO_LOGIN))
    if not user:
        user = User(login_id=DEMO_LOGIN, email=DEMO_EMAIL, password_hash=hash_secret(DEMO_PASSWORD))
        db.add(user)
        db.flush()
    else:
        user.email = DEMO_EMAIL  # keep it a valid, reachable-looking address

    taxes = {t.name: t for t in db.scalars(select(Tax))}
    today = date.today()

    # ---- structure
    wh = Warehouse(name="Main Warehouse", short_code="WH", address="Plot 14, GIDC Estate, Ahmedabad")
    nd = Warehouse(name="North Depot", short_code="ND", address="Sachin Industrial Area, Surat")
    db.add_all([wh, nd])
    db.flush()
    L = {}
    for key, w, name, code in [("WH/S1", wh, "Stock1", "Stock1"), ("WH/S2", wh, "Stock2", "Stock2"), ("WH/DISP", wh, "Dispatch", "Dispatch"),
                               ("ND/A", nd, "Rack A", "RackA"), ("ND/B", nd, "Rack B", "RackB")]:
        L[key] = Location(name=name, short_code=code, type="internal", warehouse_id=w.id)
        db.add(L[key])
    db.flush()
    for loc in L.values():
        db.refresh(loc)

    cats = {}
    for name, rate in CATEGORIES.items():
        cats[name] = Category(name=name, default_tax_id=taxes[f"GST {rate}%"].id)
        db.add(cats[name])
    db.flush()

    # ---- products with opening stock (booked as adjustments, dated a month back)
    P: dict[str, Product] = {}
    for sku, name, cat, price, hsn, rmin, rqty, opening, loc in PRODUCTS:
        p = Product(name=name, sku=sku, category_id=cats[cat].id, unit_cost=price, hsn_code=hsn, reorder_min=rmin, reorder_qty=rqty,
                    uom="Unit", tax_id=pricing.auto_tax(db, cats[cat].id).id)
        db.add(p)
        db.flush()
        P[sku] = p
        if opening:
            op = stock.adjust(db, p, L[loc], opening, user.id)
            op.contact = "Opening stock"
            op.schedule_date = today - timedelta(days=30)
            op.done_at = datetime.combine(today - timedelta(days=30), time(9, 0))
    db.flush()

    # ---- documents
    def make(kind, lines, contact, days, *, state="done", warehouse=None, src=None, dst=None):
        w, s, d = _resolve_locations(db, kind, warehouse.id if warehouse else None, L[src].id if src else None, L[dst].id if dst else None)
        when = today + timedelta(days=days)
        op = Operation(reference=stock.next_reference(db, w, kind), type=kind, status="draft", contact=contact, schedule_date=when,
                       responsible_id=user.id, warehouse_id=w.id, source_location_id=s.id, dest_location_id=d.id)
        op.lines = _make_lines(db, [LineIn(product_id=P[sku].id, quantity=q) for sku, q in lines])
        db.add(op)
        db.flush()
        if state in ("ready", "picked", "waiting", "done"):
            stock.action_todo(db, op)
            assert op.status == ("waiting" if state == "waiting" else "ready"), f"{op.reference}: {op.status} not {state}"
        if state == "picked":
            stock.action_pick(db, op)
        if state == "done":
            if kind == "OUT":
                stock.action_pick(db, op)
                stock.action_pack(db, op)
            stock.action_validate(db, op)
            op.done_at = datetime.combine(when, time(11, 30))
        if state == "cancelled":
            stock.action_cancel(db, op)
        db.flush()
        return op

    # receipts
    make("IN", [("PAPER01", 100), ("PEN001", 50)], "Office Depot Pvt Ltd", -18)
    make("IN", [("CHAIR001", 10)], "Gemini Furniture", -12)
    make("IN", [("CAM001", 10)], "Tech Mart", -9, warehouse=nd)
    make("IN", [("KEYB001", 30)], "Tech Mart", -3, state="ready")           # overdue, and covers the low keyboards
    make("IN", [("SHELF001", 12)], "Wood Corner", 4, state="draft")
    make("IN", [("BOXM01", 200)], "Lumber Inc", -6, state="cancelled")
    # deliveries that already happened
    make("OUT", [("CHAIR001", 6), ("SHELF001", 2)], "Azure Interior", -15)
    make("OUT", [("MOUSE01", 15)], "Deco Addict", -10)
    make("OUT", [("BOXM01", 40), ("TAPE001", 30)], "Ready Mat", -6)
    make("OUT", [("MARK01", 20)], "Tech Mart", -2, warehouse=nd, src="ND/B")
    # deliveries in progress
    make("OUT", [("BOXM01", 20), ("BUBBLE1", 5)], "Wood Corner", 0, state="picked")   # picked, still to pack
    make("OUT", [("MON024", 4)], "Azure Interior", 0, state="ready", src="WH/S2")     # ready, not picked yet
    make("OUT", [("MARK01", 50)], "Lumber Inc", 2, state="draft", warehouse=nd, src="ND/B")
    # deliveries blocked by stock: receive Conference Tables and the first one moves to Ready by itself
    make("OUT", [("TABLE002", 2), ("CHAIR001", 2)], "Gemini Furniture", -2, state="waiting")
    make("OUT", [("DESK002", 6)], "Deco Addict", 1, state="waiting")
    # transfers
    make("INT", [("CHAIR001", 5)], "Rebalance showroom", -5, src="WH/S1", dst="WH/S2")
    make("INT", [("PAPER01", 40)], "Restock North Depot", 1, state="ready", src="WH/S1", dst="ND/B")
    make("INT", [("TEA100", 10)], "Pantry restock", 3, state="draft", src="WH/S2", dst="WH/S1")
    # stock counts
    for sku, loc, counted, days in [("BUBBLE1", "WH/S1", 33, -3), ("COF250", "WH/S2", 44, -1)]:
        op = stock.adjust(db, P[sku], L[loc], counted, user.id)
        op.schedule_date = today + timedelta(days=days)
        op.done_at = datetime.combine(op.schedule_date, time(16, 0))

    db.commit()
    return {"products": len(P), "operations": db.query(Operation).count()}


def main() -> None:
    ap = argparse.ArgumentParser(description="Load StockSense demo data")
    ap.add_argument("--reset", action="store_true", help="delete products, documents, warehouses and locations first")
    args = ap.parse_args()

    Base.metadata.create_all(engine)
    from sqlalchemy import text
    with engine.begin() as conn:
        for stmt in MIGRATIONS:
            conn.execute(text(stmt))

    with SessionLocal() as db:
        if args.reset:
            reset(db)
            print("Cleared products, documents, warehouses and locations.")
        elif db.scalar(select(Warehouse)):
            print("Data already exists. Run with --reset to replace it with the demo data.")
            return
        info = build(db)
    print(f"Demo data loaded: {info['products']} products, {info['operations']} documents.")
    print(f"Sign in with login ID '{DEMO_LOGIN}' (password is set in backend/app/demo.py).")


if __name__ == "__main__":
    main()
