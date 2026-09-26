"""Demo dataset for presentations.

    docker compose exec backend python -m app.demo            # add the demo data (skips if already present)
    docker compose exec backend python -m app.demo --reset    # wipe products/documents/warehouses and rebuild

Builds two warehouses, five categories with default taxes, 18 products with HSN codes and reorder rules, and
a realistic mix of receipts, deliveries, transfers and adjustments in every status. See DEMO.md for a
click-through script. Users and taxes are never deleted.
"""
import argparse
import json
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select

from . import pricing, stock
from .db import SessionLocal, engine
from .audit import AuditLog
from .migrations import run_migrations
from .models import (
    Base, Category, Location, Operation, OperationLine, Party, Product, Sequence, StockQuant, Tax, User, Warehouse,
)
from .routers.operations import LineIn, _make_lines, _resolve_locations
from .routers.parties import gstin_check_char
from .security import hash_secret
from .seed import seed_taxes, seed_virtual_locations

# Demo account. Change it if this is ever exposed beyond a local demo.
DEMO_LOGIN = "demo_admin"
DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "Demo@12345"

CATEGORIES = {"Furniture": 18, "Electronics": 18, "Stationery": 12, "Packaging": 12, "Pantry": 5}
# what we pay, as a share of the sales price, so the margin report has something to show
COST_RATIO = {"Furniture": 0.62, "Electronics": 0.74, "Stationery": 0.68, "Packaging": 0.60, "Pantry": 0.70}

# name, type, first 14 characters of the GSTIN (the check digit is computed), phone, address
PARTIES = [
    ("Office Depot Pvt Ltd", "vendor", "24AABCO4589E1Z", "+91 79 4000 1100", "12 CG Road, Navrangpura, Ahmedabad"),
    ("Gemini Furniture", "both", "27AAECG4321M1Z", "+91 20 6700 2200", "Baner Road, Pune"),
    ("Tech Mart", "both", "29AAFCT7788P1Z", "+91 80 4100 3300", "Brigade Road, Bengaluru"),
    ("Wood Corner", "both", "24AAHFW2210R1Z", "+91 281 2400 440", "Aji GIDC, Rajkot"),
    ("Lumber Inc", "both", "33AAACL9012B1Z", "+91 44 4200 5500", "Ambattur Industrial Estate, Chennai"),
    ("Azure Interior", "customer", "27AAJCA5566N1Z", "+91 22 6100 7700", "Andheri East, Mumbai"),
    ("Deco Addict", "customer", "07AAKCD3344H1Z", "+91 11 4300 8800", "Nehru Place, New Delhi"),
    ("Ready Mat", "customer", "24AALCR1122G1Z", "+91 261 2200 990", "Sachin GIDC, Surat"),
]

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
    for model in (AuditLog, OperationLine, Operation, StockQuant, Sequence, Product, Category, Party):
        db.execute(delete(model))
    db.execute(delete(Location).where(Location.warehouse_id.isnot(None)))
    db.execute(delete(Warehouse))
    db.commit()


def build(db) -> dict:
    seed_virtual_locations(db)
    seed_taxes(db)

    def ensure_user(login: str, role: str, email: str) -> User:
        u = db.scalar(select(User).where(User.login_id == login))
        if not u:
            u = User(login_id=login, email=email, password_hash=hash_secret(DEMO_PASSWORD))
            db.add(u)
            db.flush()
        u.role, u.email, u.active = role, email, True  # keep the demo people valid, active and correctly ranked
        return u

    user = ensure_user(DEMO_LOGIN, "admin", DEMO_EMAIL)
    mgr = ensure_user("demo_manager", "manager", "manager@example.com")
    staff = ensure_user("demo_staff", "staff", "staff@example.com")

    def note(actor, action, entity, entity_id, label, at, detail=None, changes=None):
        """The demo builds data through the service layer, so write the activity log entries the API would have."""
        at = min(at, datetime.utcnow() - timedelta(minutes=30))  # history can't be in the future
        db.add(AuditLog(at=at, user_id=actor.id, user_login=actor.login_id, action=action, entity=entity, entity_id=entity_id,
                        label=label, detail=detail, changes=json.dumps(changes) if changes else None))

    taxes = {t.name: t for t in db.scalars(select(Tax))}
    today = date.today()

    # ---- structure
    wh = Warehouse(name="Main Warehouse", short_code="WH", address="Plot 14, GIDC Estate, Ahmedabad")
    nd = Warehouse(name="North Depot", short_code="ND", address="Sachin Industrial Area, Surat")
    db.add_all([wh, nd])
    db.flush()
    for w in (wh, nd):
        note(user, "create", "warehouse", w.id, f"{w.short_code} · {w.name}", datetime.combine(today - timedelta(days=35), time(9, 0)))
    L = {}
    for key, w, name, code in [("WH/S1", wh, "Stock1", "Stock1"), ("WH/S2", wh, "Stock2", "Stock2"), ("WH/DISP", wh, "Dispatch", "Dispatch"),
                               ("ND/A", nd, "Rack A", "RackA"), ("ND/B", nd, "Rack B", "RackB")]:
        L[key] = Location(name=name, short_code=code, type="internal", warehouse_id=w.id)
        db.add(L[key])
    db.flush()
    for loc in L.values():
        db.refresh(loc)

    parties = {}
    for name, kind, first14, phone, address in PARTIES:
        parties[name] = Party(name=name, kind=kind, gstin=first14 + gstin_check_char(first14), phone=phone, address=address,
                              email=f"accounts@{name.lower().replace(' ', '').replace('pvtltd', '')}.example.com")
        db.add(parties[name])
        db.flush()
        note(mgr, "create", "contact", parties[name].id, name, datetime.combine(today - timedelta(days=33), time(10, 0)))

    cats = {}
    for name, rate in CATEGORIES.items():
        cats[name] = Category(name=name, default_tax_id=taxes[f"GST {rate}%"].id)
        db.add(cats[name])
    db.flush()

    # ---- products with opening stock (booked as adjustments, dated a month back)
    P: dict[str, Product] = {}
    for sku, name, cat, price, hsn, rmin, rqty, opening, loc in PRODUCTS:
        cost = round(price * COST_RATIO[cat], 2)
        p = Product(name=name, sku=sku, category_id=cats[cat].id, unit_cost=price, cost_price=cost, avg_cost=cost, hsn_code=hsn,
                    reorder_min=rmin, reorder_qty=rqty, uom="Unit", tax_id=pricing.auto_tax(db, cats[cat].id).id)
        db.add(p)
        db.flush()
        P[sku] = p
        note(mgr, "create", "product", p.id, f"{p.sku} · {p.name}", datetime.combine(today - timedelta(days=31), time(9, 0)))
        if opening:
            op = stock.adjust(db, p, L[loc], opening, user.id)
            op.contact = "Opening stock"
            op.schedule_date = today - timedelta(days=30)
            op.done_at = datetime.combine(today - timedelta(days=30), time(9, 0))
    db.flush()

    note(mgr, "update", "product", P["CHAIR001"].id, "CHAIR001 · Office Chair", datetime.combine(today - timedelta(days=20), time(15, 0)),
         changes={"unit_cost": [4000, 4200], "reorder_min": [5, 8]})
    note(user, "update", "tax", taxes["GST 18%"].id, "GST 18%", datetime.combine(today - timedelta(days=25), time(11, 0)),
         changes={"is_default": [False, True]})
    note(user, "role", "user", mgr.id, mgr.login_id, datetime.combine(today - timedelta(days=36), time(9, 30)), changes={"role": ["staff", "manager"]})

    # ---- documents
    def make(kind, lines, contact, days, *, state="done", warehouse=None, src=None, dst=None, partial=None):
        actor = staff if kind == "INT" else mgr  # managers prepare receipts and deliveries; staff run transfers
        w, s, d = _resolve_locations(db, kind, warehouse.id if warehouse else None, L[src].id if src else None, L[dst].id if dst else None)
        when = today + timedelta(days=days)
        party = parties.get(contact) if kind in ("IN", "OUT") else None
        op = Operation(reference=stock.next_reference(db, w, kind), type=kind, status="draft", contact=contact, schedule_date=when,
                       responsible_id=actor.id, warehouse_id=w.id, source_location_id=s.id, dest_location_id=d.id,
                       party_id=party.id if party else None)
        # a line is (sku, qty) or (sku, qty, unit_price) when the price paid differs from the default
        op.lines = _make_lines(db, [LineIn(product_id=P[l[0]].id, quantity=l[1], unit_price=l[2] if len(l) > 2 else None) for l in lines], kind)
        db.add(op)
        db.flush()
        t0 = datetime.combine(when - timedelta(days=2), time(9, 30))
        note(actor, "create", "operation", op.id, op.reference, t0, detail=f"{len(op.lines)} line{'s' if len(op.lines) != 1 else ''}")
        if state in ("ready", "picked", "waiting", "done"):
            msg = stock.action_todo(db, op)
            assert op.status == ("waiting" if state == "waiting" else "ready"), f"{op.reference}: {op.status} not {state}"
            note(actor, "todo", "operation", op.id, op.reference, t0 + timedelta(hours=1), detail=msg or "now ready")
        if state == "picked":
            stock.action_pick(db, op)
            note(staff, "pick", "operation", op.id, op.reference, datetime.combine(when, time(10, 0)), detail="now ready")
        if state == "done":
            if kind == "OUT":
                stock.action_pick(db, op)
                stock.action_pack(db, op)
                note(staff, "pick", "operation", op.id, op.reference, datetime.combine(when, time(10, 0)), detail="now ready")
                note(staff, "pack", "operation", op.id, op.reference, datetime.combine(when, time(10, 30)), detail="now ready")
            msg = stock.action_validate(db, op, {op.lines[i].id: q for i, q in (partial or {}).items()} or None)
            op.done_at = datetime.combine(when, time(11, 30))
            note(staff if kind == "OUT" else actor, "validate", "operation", op.id, op.reference, op.done_at, detail=msg or "now done")
            bo = db.scalar(select(Operation).where(Operation.backorder_of_id == op.id))
            if bo:
                note(actor, "create", "operation", bo.id, bo.reference, op.done_at, detail=f"backorder of {op.reference}")
        if state == "cancelled":
            stock.action_cancel(db, op)
            note(actor, "cancel", "operation", op.id, op.reference, t0 + timedelta(days=1), detail="now cancelled")
        db.flush()
        return op

    # receipts
    make("IN", [("PAPER01", 100, 240), ("PEN001", 50)], "Office Depot Pvt Ltd", -18)   # paper bought dearer: the average moves
    make("IN", [("CHAIR001", 10)], "Gemini Furniture", -12, partial={0: 6})          # 6 of 10 arrived: backorder for 4 is still open
    make("IN", [("CAM001", 10)], "Tech Mart", -9, warehouse=nd)
    make("IN", [("KEYB001", 30)], "Tech Mart", -3, state="ready")           # overdue, and covers the low keyboards
    make("IN", [("SHELF001", 12)], "Wood Corner", 4, state="draft")
    make("IN", [("BOXM01", 200)], "Lumber Inc", -6, state="cancelled")
    # deliveries that already happened
    make("OUT", [("CHAIR001", 6), ("SHELF001", 2)], "Azure Interior", -15)
    make("OUT", [("MOUSE01", 15)], "Deco Addict", -10)
    make("OUT", [("BOXM01", 40), ("TAPE001", 30)], "Ready Mat", -6, partial={1: 20})  # shipped 20 of 30 tape: backorder of 10
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
    run_migrations(engine)

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
