"""Warehouses, locations, taxes and category tax defaults. Everyone may read; only administrators may change."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import audit, lifecycle
from ..db import get_db
from ..deps import admin, current_user
from ..models import Category, Location, Product, Sequence, StockQuant, Tax, User, Warehouse

router = APIRouter(tags=["settings"], dependencies=[Depends(current_user)])


class WarehouseIn(BaseModel):
    name: str = Field(max_length=100)
    short_code: str = Field(max_length=10)
    address: str | None = Field(default=None, max_length=255)


class LocationIn(BaseModel):
    name: str = Field(max_length=100)
    short_code: str = Field(max_length=20)
    warehouse_id: int
    type: str = "internal"


def wh_out(w: Warehouse) -> dict:
    return {"id": w.id, "name": w.name, "short_code": w.short_code, "address": w.address, "active": w.active}


def loc_out(l: Location) -> dict:
    return {
        "id": l.id,
        "name": l.name,
        "short_code": l.short_code,
        "full_name": l.full_name,
        "type": l.type,
        "warehouse_id": l.warehouse_id,
        "active": l.active,
    }


# ---------------------------------------------------------------- warehouses
@router.get("/warehouses")
def list_warehouses(include_archived: bool = False, db: Session = Depends(get_db)):
    stmt = select(Warehouse).order_by(Warehouse.id)
    if not include_archived:
        stmt = stmt.where(Warehouse.active.is_(True))
    return [wh_out(w) for w in db.scalars(stmt)]


@router.post("/warehouses", status_code=201)
def create_warehouse(body: WarehouseIn, db: Session = Depends(get_db), actor: User = Depends(admin)):
    code = body.short_code.strip().upper()
    if not code or not body.name.strip():
        raise HTTPException(422, "Name and short code are required")
    if db.scalar(select(Warehouse).where(Warehouse.short_code == code)):
        raise HTTPException(409, "Short code already used")
    w = Warehouse(name=body.name.strip(), short_code=code, address=body.address)
    db.add(w)
    db.flush()
    audit.record(db, actor, "create", "warehouse", w.id, f"{w.short_code} · {w.name}")
    db.commit()
    return wh_out(w)


@router.put("/warehouses/{wid}")
def update_warehouse(wid: int, body: WarehouseIn, db: Session = Depends(get_db), actor: User = Depends(admin)):
    w = db.get(Warehouse, wid)
    if not w:
        raise HTTPException(404, "Warehouse not found")
    code = body.short_code.strip().upper()
    clash = db.scalar(select(Warehouse).where(Warehouse.short_code == code, Warehouse.id != wid))
    if clash:
        raise HTTPException(409, "Short code already used")
    old = audit.snapshot(w, ["name", "short_code", "address"])
    w.name, w.short_code, w.address = body.name.strip(), code, body.address
    if changes := audit.diff(old, audit.snapshot(w, ["name", "short_code", "address"])):
        audit.record(db, actor, "update", "warehouse", w.id, f"{w.short_code} · {w.name}", changes=changes)
    db.commit()
    return wh_out(w)


@router.post("/warehouses/{wid}/archive")
def archive_warehouse(wid: int, db: Session = Depends(get_db), actor: User = Depends(admin)):
    w = db.get(Warehouse, wid)
    if not w:
        raise HTTPException(404, "Warehouse not found")
    if reason := lifecycle.archive_blocker(lifecycle.warehouse_usage(db, wid), "This warehouse"):
        raise HTTPException(409, reason)
    w.active = False
    for loc in w.locations:
        loc.active = False
    audit.record(db, actor, "archive", "warehouse", w.id, f"{w.short_code} · {w.name}")
    db.commit()
    return wh_out(w)


@router.post("/warehouses/{wid}/restore")
def restore_warehouse(wid: int, db: Session = Depends(get_db), actor: User = Depends(admin)):
    w = db.get(Warehouse, wid)
    if not w:
        raise HTTPException(404, "Warehouse not found")
    w.active = True
    for loc in w.locations:
        loc.active = True
    audit.record(db, actor, "restore", "warehouse", w.id, f"{w.short_code} · {w.name}")
    db.commit()
    return wh_out(w)


@router.delete("/warehouses/{wid}")
def delete_warehouse(wid: int, db: Session = Depends(get_db), actor: User = Depends(admin)):
    w = db.get(Warehouse, wid)
    if not w:
        raise HTTPException(404, "Warehouse not found")
    if reason := lifecycle.delete_blocker(lifecycle.warehouse_usage(db, wid), "This warehouse"):
        raise HTTPException(409, reason)
    label = f"{w.short_code} · {w.name}"
    loc_ids = [l.id for l in w.locations]
    if loc_ids:
        db.execute(delete(StockQuant).where(StockQuant.location_id.in_(loc_ids)))
        for loc in list(w.locations):
            db.delete(loc)
    db.execute(delete(Sequence).where(Sequence.key.like(f"{wid}/%")))
    db.delete(w)
    audit.record(db, actor, "delete", "warehouse", wid, label)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- locations
@router.get("/locations")
def list_locations(
    warehouse_id: int | None = None, internal_only: bool = False, include_archived: bool = False, db: Session = Depends(get_db)
):
    stmt = select(Location).order_by(Location.id)
    if warehouse_id:
        stmt = stmt.where(Location.warehouse_id == warehouse_id)
    if internal_only:
        stmt = stmt.where(Location.type == "internal")
    if not include_archived:
        stmt = stmt.where(Location.active.is_(True))
    return [loc_out(l) for l in db.scalars(stmt)]


@router.post("/locations", status_code=201)
def create_location(body: LocationIn, db: Session = Depends(get_db), actor: User = Depends(admin)):
    wh = db.get(Warehouse, body.warehouse_id)
    if not wh:
        raise HTTPException(404, "Warehouse not found")
    if not wh.active:
        raise HTTPException(422, "That warehouse is archived")
    l = Location(name=body.name.strip(), short_code=body.short_code.strip(), warehouse_id=body.warehouse_id, type="internal")
    db.add(l)
    db.flush()
    audit.record(db, actor, "create", "location", l.id, f"{wh.short_code}/{l.short_code}")
    db.commit()
    return loc_out(l)


@router.put("/locations/{lid}")
def update_location(lid: int, body: LocationIn, db: Session = Depends(get_db), actor: User = Depends(admin)):
    l = db.get(Location, lid)
    if not l or l.type != "internal":
        raise HTTPException(404, "Location not found")
    fields = ["name", "short_code", "warehouse_id"]
    old = audit.snapshot(l, fields)
    l.name, l.short_code, l.warehouse_id = body.name.strip(), body.short_code.strip(), body.warehouse_id
    if changes := audit.diff(old, audit.snapshot(l, fields)):
        audit.record(db, actor, "update", "location", l.id, l.full_name, changes=changes)
    db.commit()
    return loc_out(l)


def _stock_location(db: Session, lid: int) -> Location:
    l = db.get(Location, lid)
    if not l or l.type != "internal":
        raise HTTPException(404, "Location not found")
    return l


@router.post("/locations/{lid}/archive")
def archive_location(lid: int, db: Session = Depends(get_db), actor: User = Depends(admin)):
    l = _stock_location(db, lid)
    if reason := lifecycle.archive_blocker(lifecycle.location_usage(db, lid), "This location"):
        raise HTTPException(409, reason)
    l.active = False
    audit.record(db, actor, "archive", "location", l.id, l.full_name)
    db.commit()
    return loc_out(l)


@router.post("/locations/{lid}/restore")
def restore_location(lid: int, db: Session = Depends(get_db), actor: User = Depends(admin)):
    l = _stock_location(db, lid)
    if l.warehouse and not l.warehouse.active:
        raise HTTPException(409, "Restore the warehouse first")
    l.active = True
    audit.record(db, actor, "restore", "location", l.id, l.full_name)
    db.commit()
    return loc_out(l)


@router.delete("/locations/{lid}")
def delete_location(lid: int, db: Session = Depends(get_db), actor: User = Depends(admin)):
    l = _stock_location(db, lid)
    if reason := lifecycle.delete_blocker(lifecycle.location_usage(db, lid), "This location"):
        raise HTTPException(409, reason)
    label = l.full_name
    db.execute(delete(StockQuant).where(StockQuant.location_id == lid))
    db.delete(l)
    audit.record(db, actor, "delete", "location", lid, label)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- taxes
class TaxIn(BaseModel):
    name: str = Field(max_length=60)
    rate: float
    kind: str = "GST"
    active: bool = True
    is_default: bool = False


def tax_out(t: Tax) -> dict:
    return {"id": t.id, "name": t.name, "rate": t.rate, "kind": t.kind, "active": t.active, "is_default": t.is_default}


def _check_tax(body: TaxIn) -> None:
    if not body.name.strip():
        raise HTTPException(422, "Name is required")
    if not 0 <= body.rate <= 100:
        raise HTTPException(422, "Rate must be between 0 and 100")
    if body.kind not in ("GST", "OTHER"):
        raise HTTPException(422, "Type must be GST or OTHER")


def _apply_default(db: Session, tax: Tax) -> None:
    if tax.is_default:
        for other in db.scalars(select(Tax).where(Tax.id != tax.id, Tax.is_default.is_(True))):
            other.is_default = False


@router.get("/taxes")
def list_taxes(include_inactive: bool = False, db: Session = Depends(get_db)):
    stmt = select(Tax).order_by(Tax.kind, Tax.rate, Tax.id)
    if not include_inactive:
        stmt = stmt.where(Tax.active.is_(True))
    return [tax_out(t) for t in db.scalars(stmt)]


@router.post("/taxes", status_code=201)
def create_tax(body: TaxIn, db: Session = Depends(get_db), actor: User = Depends(admin)):
    _check_tax(body)
    if db.scalar(select(Tax).where(Tax.name == body.name.strip())):
        raise HTTPException(409, "A tax with this name already exists")
    t = Tax(name=body.name.strip(), rate=body.rate, kind=body.kind, active=body.active, is_default=body.is_default and body.active)
    db.add(t)
    db.flush()
    _apply_default(db, t)
    audit.record(db, actor, "create", "tax", t.id, t.name, detail=f"{t.rate:g}%")
    db.commit()
    return tax_out(t)


@router.put("/taxes/{tid}")
def update_tax(tid: int, body: TaxIn, db: Session = Depends(get_db), actor: User = Depends(admin)):
    """Editing a rate affects new and draft documents only; validated ones keep the rate they were created with."""
    _check_tax(body)
    t = db.get(Tax, tid)
    if not t:
        raise HTTPException(404, "Tax not found")
    if db.scalar(select(Tax).where(Tax.name == body.name.strip(), Tax.id != tid)):
        raise HTTPException(409, "A tax with this name already exists")
    fields = ["name", "rate", "kind", "active", "is_default"]
    old = audit.snapshot(t, fields)
    t.name, t.rate, t.kind, t.active = body.name.strip(), body.rate, body.kind, body.active
    t.is_default = body.is_default and body.active
    db.flush()
    _apply_default(db, t)
    if changes := audit.diff(old, audit.snapshot(t, fields)):
        audit.record(db, actor, "update", "tax", t.id, t.name, changes=changes)
    db.commit()
    return tax_out(t)


class CategoryTaxIn(BaseModel):
    default_tax_id: int | None = None


@router.get("/category-taxes")
def category_taxes(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Product.category_id, func.count()).group_by(Product.category_id)).all())
    return [
        {"id": c.id, "name": c.name, "default_tax_id": c.default_tax_id, "products": counts.get(c.id, 0)}
        for c in db.scalars(select(Category).order_by(Category.name))
    ]


@router.put("/category-taxes/{cid}")
def set_category_tax(cid: int, body: CategoryTaxIn, db: Session = Depends(get_db), actor: User = Depends(admin)):
    c = db.get(Category, cid)
    if not c:
        raise HTTPException(404, "Category not found")
    if body.default_tax_id and not db.get(Tax, body.default_tax_id):
        raise HTTPException(404, "Tax not found")
    old = c.default_tax_id
    c.default_tax_id = body.default_tax_id
    if old != c.default_tax_id:
        audit.record(db, actor, "update", "category", c.id, c.name, changes={"default_tax_id": [old, c.default_tax_id]})
    db.commit()
    return {"id": c.id, "default_tax_id": c.default_tax_id}
