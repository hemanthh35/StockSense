from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Category, Location, Product, Tax, Warehouse

router = APIRouter(tags=["settings"], dependencies=[Depends(current_user)])


class WarehouseIn(BaseModel):
    name: str
    short_code: str
    address: str | None = None


class LocationIn(BaseModel):
    name: str
    short_code: str
    warehouse_id: int
    type: str = "internal"


def wh_out(w: Warehouse) -> dict:
    return {"id": w.id, "name": w.name, "short_code": w.short_code, "address": w.address}


def loc_out(l: Location) -> dict:
    return {
        "id": l.id,
        "name": l.name,
        "short_code": l.short_code,
        "full_name": l.full_name,
        "type": l.type,
        "warehouse_id": l.warehouse_id,
    }


@router.get("/warehouses")
def list_warehouses(db: Session = Depends(get_db)):
    return [wh_out(w) for w in db.scalars(select(Warehouse).order_by(Warehouse.id))]


@router.post("/warehouses", status_code=201)
def create_warehouse(body: WarehouseIn, db: Session = Depends(get_db)):
    code = body.short_code.strip().upper()
    if db.scalar(select(Warehouse).where(Warehouse.short_code == code)):
        raise HTTPException(409, "Short code already used")
    w = Warehouse(name=body.name.strip(), short_code=code, address=body.address)
    db.add(w)
    db.commit()
    return wh_out(w)


@router.put("/warehouses/{wid}")
def update_warehouse(wid: int, body: WarehouseIn, db: Session = Depends(get_db)):
    w = db.get(Warehouse, wid)
    if not w:
        raise HTTPException(404, "Warehouse not found")
    code = body.short_code.strip().upper()
    clash = db.scalar(select(Warehouse).where(Warehouse.short_code == code, Warehouse.id != wid))
    if clash:
        raise HTTPException(409, "Short code already used")
    w.name, w.short_code, w.address = body.name.strip(), code, body.address
    db.commit()
    return wh_out(w)


@router.get("/locations")
def list_locations(warehouse_id: int | None = None, internal_only: bool = False, db: Session = Depends(get_db)):
    stmt = select(Location).order_by(Location.id)
    if warehouse_id:
        stmt = stmt.where(Location.warehouse_id == warehouse_id)
    if internal_only:
        stmt = stmt.where(Location.type == "internal")
    return [loc_out(l) for l in db.scalars(stmt)]


@router.post("/locations", status_code=201)
def create_location(body: LocationIn, db: Session = Depends(get_db)):
    if not db.get(Warehouse, body.warehouse_id):
        raise HTTPException(404, "Warehouse not found")
    l = Location(name=body.name.strip(), short_code=body.short_code.strip(), warehouse_id=body.warehouse_id, type="internal")
    db.add(l)
    db.commit()
    return loc_out(l)


@router.put("/locations/{lid}")
def update_location(lid: int, body: LocationIn, db: Session = Depends(get_db)):
    l = db.get(Location, lid)
    if not l or l.type != "internal":
        raise HTTPException(404, "Location not found")
    l.name, l.short_code, l.warehouse_id = body.name.strip(), body.short_code.strip(), body.warehouse_id
    db.commit()
    return loc_out(l)


class TaxIn(BaseModel):
    name: str
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
def create_tax(body: TaxIn, db: Session = Depends(get_db)):
    _check_tax(body)
    if db.scalar(select(Tax).where(Tax.name == body.name.strip())):
        raise HTTPException(409, "A tax with this name already exists")
    t = Tax(name=body.name.strip(), rate=body.rate, kind=body.kind, active=body.active, is_default=body.is_default and body.active)
    db.add(t)
    db.flush()
    _apply_default(db, t)
    db.commit()
    return tax_out(t)


@router.put("/taxes/{tid}")
def update_tax(tid: int, body: TaxIn, db: Session = Depends(get_db)):
    """Editing a rate affects new and draft documents only; validated ones keep the rate they were created with."""
    _check_tax(body)
    t = db.get(Tax, tid)
    if not t:
        raise HTTPException(404, "Tax not found")
    if db.scalar(select(Tax).where(Tax.name == body.name.strip(), Tax.id != tid)):
        raise HTTPException(409, "A tax with this name already exists")
    t.name, t.rate, t.kind, t.active = body.name.strip(), body.rate, body.kind, body.active
    t.is_default = body.is_default and body.active
    db.flush()
    _apply_default(db, t)
    db.commit()
    return tax_out(t)


class CategoryTaxIn(BaseModel):
    default_tax_id: int | None = None


@router.get("/category-taxes")
def category_taxes(db: Session = Depends(get_db)):
    return [
        {"id": c.id, "name": c.name, "default_tax_id": c.default_tax_id, "products": db.query(Product).filter(Product.category_id == c.id).count()}
        for c in db.scalars(select(Category).order_by(Category.name))
    ]


@router.put("/category-taxes/{cid}")
def set_category_tax(cid: int, body: CategoryTaxIn, db: Session = Depends(get_db)):
    c = db.get(Category, cid)
    if not c:
        raise HTTPException(404, "Category not found")
    if body.default_tax_id and not db.get(Tax, body.default_tax_id):
        raise HTTPException(404, "Tax not found")
    c.default_tax_id = body.default_tax_id
    db.commit()
    return {"id": c.id, "default_tax_id": c.default_tax_id}
