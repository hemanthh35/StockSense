"""CSV export of the main lists and CSV import of products (preview first, then apply)."""
import csv
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import stock
from ..db import get_db
from ..deps import current_user
from ..models import Category, Location, Product, Tax, User
from .inventory import stock_list
from .operations import list_operations, move_history
from .products import product_out

router = APIRouter(tags=["csv"])

MAX_ROWS = 2000
MAX_CHARS = 2_000_000


def _safe(v):
    """Neutralise spreadsheet formula injection (=, +, -, @) in text cells."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return "" if v is None else v


def _csv(filename: str, header: list[str], rows: list[list]) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([_safe(c) for c in r])
    return Response(
        content="﻿" + buf.getvalue(),  # BOM so Excel opens UTF-8 correctly
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ------------------------------------------------------------------ exports
@router.get("/export/products.csv")
def export_products(include_archived: bool = False, db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(Product).order_by(Product.name)
    if not include_archived:
        stmt = stmt.where(Product.active.is_(True))
    rows = []
    for p in db.scalars(stmt):
        o = product_out(db, p)
        rows.append([p.sku, p.name, o["category"], p.uom, p.unit_cost, p.hsn_code, o["tax"]["name"] if o["tax"] else "None",
                     p.reorder_min, p.reorder_qty, o["on_hand"], "yes" if p.active else "archived"])
    return _csv("products.csv", ["sku", "name", "category", "uom", "unit_cost", "hsn_code", "tax", "reorder_min", "reorder_qty", "on_hand", "status"], rows)


@router.get("/export/stock.csv")
def export_stock(q: str | None = None, warehouse_id: int | None = None, category_id: int | None = None,
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = []
    for r in stock_list(q=q, warehouse_id=warehouse_id, category_id=category_id, db=db, _=user):
        locs = r["locations"] or [{"location": "", "on_hand": 0, "free_to_use": 0}]
        for l in locs:
            rows.append([r["sku"], r["name"], r["category"], l["location"], l["on_hand"], l["free_to_use"], r["unit_cost"], round(l["on_hand"] * r["unit_cost"], 2)])
    return _csv("stock.csv", ["sku", "product", "category", "location", "on_hand", "free_to_use", "unit_cost", "stock_value"], rows)


@router.get("/export/moves.csv")
def export_moves(q: str | None = None, status: str | None = None, direction: str | None = None, type: str | None = None,
                 warehouse_id: int | None = None, location_id: int | None = None, category_id: int | None = None,
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    moves = move_history(q=q, status=status, direction=direction, type=type, warehouse_id=warehouse_id,
                         location_id=location_id, category_id=category_id, db=db, _=user)
    rows = [[m["reference"], m["type"], m["contact"], m["product"], m["from"], m["to"], m["quantity"], m["direction"], m["date"], m["status"]] for m in moves]
    return _csv("move-history.csv", ["reference", "type", "contact", "product", "from", "to", "quantity", "direction", "date", "status"], rows)


@router.get("/export/operations.csv")
def export_operations(type: str | None = None, status: str | None = None, q: str | None = None, warehouse_id: int | None = None,
                      location_id: int | None = None, category_id: int | None = None,
                      db: Session = Depends(get_db), user: User = Depends(current_user)):
    ops = list_operations(type=type, status=status, q=q, warehouse_id=warehouse_id, location_id=location_id,
                          category_id=category_id, db=db, _=user)
    rows = [[o["reference"], o["type_label"], o["status"], o["contact"], o["schedule_date"], o["warehouse"]["short_code"],
             o["source_location"]["name"], o["dest_location"]["name"], o["subtotal"], o["tax_total"], o["total"], o["responsible"]] for o in ops]
    return _csv("operations.csv", ["reference", "type", "status", "contact", "schedule_date", "warehouse", "from", "to", "subtotal", "tax", "total", "responsible"], rows)


# ------------------------------------------------------------------ product import
ALIASES = {
    "product": "name", "product_name": "name", "item": "name",
    "code": "sku", "sku_code": "sku", "product_code": "sku",
    "unit_price": "unit_cost", "price": "unit_cost", "cost": "unit_cost",
    "hsn": "hsn_code", "hsn_sac": "hsn_code", "hsn/sac": "hsn_code", "hsn_sac_code": "hsn_code",
    "gst": "tax", "tax_rate": "tax",
    "unit": "uom", "unit_of_measure": "uom",
    "min": "reorder_min", "reorder_level": "reorder_min", "reorder_at": "reorder_min",
    "reorder_quantity": "reorder_qty", "order_qty": "reorder_qty",
    "stock": "initial_stock", "opening_stock": "initial_stock", "qty": "initial_stock", "quantity": "initial_stock",
}
NUMERIC = ("unit_cost", "reorder_min", "reorder_qty", "initial_stock")


class ImportIn(BaseModel):
    csv: str
    dry_run: bool = True


def _norm(h: str) -> str:
    h = re.sub(r"\s+", "_", (h or "").strip().lower().lstrip("﻿"))
    return ALIASES.get(h, h)


def _number(raw: str, field: str) -> float:
    try:
        v = float(raw.replace(",", ""))
    except ValueError:
        raise ValueError(f"{field} must be a number")
    if v < 0:
        raise ValueError(f"{field} can't be negative")
    return v


def _match_tax(raw: str, taxes: list[Tax]):
    """blank -> 'auto' (leave to defaults) | 'none' | Tax. Accepts a tax name or a bare rate like 18 / 18%."""
    t = raw.strip()
    if not t:
        return "auto"
    if t.lower() in ("none", "no tax", "no", "-", "exempt"):
        return "none"
    for tax in taxes:
        if tax.name.lower() == t.lower():
            return tax
    m = re.fullmatch(r"(?:gst\s*)?(\d+(?:\.\d+)?)\s*%?", t.lower())
    if m:
        rate = float(m.group(1))
        for tax in sorted(taxes, key=lambda x: x.kind != "GST"):
            if tax.rate == rate:
                return tax
    raise ValueError(f"unknown tax '{t}'")


@router.post("/products/import")
def import_products(body: ImportIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    text = body.csv.lstrip("﻿")
    if len(text) > MAX_CHARS:
        raise HTTPException(413, "File is too large (2 MB max)")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(422, "The file is empty")
    fields = [_norm(h) for h in reader.fieldnames]
    if "name" not in fields or "sku" not in fields:
        raise HTTPException(422, "The file needs at least 'name' and 'sku' columns")

    taxes = list(db.scalars(select(Tax).where(Tax.active.is_(True))))
    cats = {c.name.lower(): c for c in db.scalars(select(Category))}
    loc = db.scalar(select(Location).where(Location.type == "internal", Location.active.is_(True)).order_by(Location.id))
    seen: set[str] = set()
    plan, results = [], []

    for i, raw_row in enumerate(reader, start=2):
        if i - 1 > MAX_ROWS:
            raise HTTPException(413, f"Too many rows ({MAX_ROWS} max)")
        row = {_norm(k): (v or "").strip() for k, v in raw_row.items() if k is not None}
        if not any(row.values()):
            continue
        sku, name = row.get("sku", "").upper(), row.get("name", "")
        try:
            if not sku or not name:
                raise ValueError("name and sku are required")
            if sku in seen:
                raise ValueError("duplicate SKU in this file")
            seen.add(sku)
            nums = {f: _number(row[f], f) for f in NUMERIC if row.get(f, "") != ""}
            tax = _match_tax(row["tax"], taxes) if "tax" in row else "auto"
            existing = db.scalar(select(Product).where(Product.sku == sku))
            if nums.get("initial_stock") and not existing and not loc:
                raise ValueError("no stock location exists for the opening stock")
            plan.append((existing, sku, name, row, nums, tax))
            results.append({"row": i, "sku": sku, "name": name, "action": "update" if existing else "create", "message": ""})
        except ValueError as e:
            results.append({"row": i, "sku": sku, "name": name, "action": "error", "message": str(e)})

    created = sum(1 for r in results if r["action"] == "create")
    updated = sum(1 for r in results if r["action"] == "update")
    errors = [r for r in results if r["action"] == "error"]

    if not body.dry_run:
        for existing, sku, name, row, nums, tax in plan:
            cat = None
            cname = row.get("category", "")
            if cname:
                cat = cats.get(cname.lower())
                if not cat:
                    cat = Category(name=cname)
                    db.add(cat)
                    db.flush()
                    cats[cname.lower()] = cat
            p = existing or Product(sku=sku, name=name)
            p.name = name
            if "category" in row:
                p.category_id = cat.id if cat else None
            if row.get("uom"):
                p.uom = row["uom"]
            for f in ("unit_cost", "reorder_min", "reorder_qty"):
                if f in nums:
                    setattr(p, f, nums[f])
            if "hsn_code" in row:
                p.hsn_code = row["hsn_code"] or None
            if tax == "none":
                p.tax_id = None
            elif tax != "auto":
                p.tax_id = tax.id
            elif not existing:
                from .. import pricing
                auto = pricing.auto_tax(db, p.category_id)
                p.tax_id = auto.id if auto else None
            if not existing:
                db.add(p)
                db.flush()
                if nums.get("initial_stock"):
                    stock.adjust(db, p, loc, nums["initial_stock"], user.id)
        db.commit()

    return {
        "dry_run": body.dry_run,
        "created": created,
        "updated": updated,
        "skipped": len(errors),
        "errors": errors,
        "rows": results[:200],
    }
