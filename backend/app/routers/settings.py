from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import Location, Warehouse

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
