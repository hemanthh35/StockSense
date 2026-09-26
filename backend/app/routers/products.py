from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import stock
from ..db import get_db
from ..deps import current_user
from ..models import Category, Location, Product, StockQuant, User

router = APIRouter(tags=["products"])


class CategoryIn(BaseModel):
    name: str


class ProductIn(BaseModel):
    name: str
    sku: str
    category_id: int | None = None
    uom: str = "Unit"
    unit_cost: float = 0
    reorder_min: float = 0
    reorder_qty: float = 0
    initial_stock: float = 0
    initial_location_id: int | None = None


def product_out(db: Session, p: Product, on_hand: float | None = None) -> dict:
    if on_hand is None:
        on_hand = float(
            db.scalar(
                select(func.coalesce(func.sum(StockQuant.quantity), 0))
                .join(Location, Location.id == StockQuant.location_id)
                .where(StockQuant.product_id == p.id, Location.type == "internal")
            )
        )
    return {
        "id": p.id,
        "name": p.name,
        "sku": p.sku,
        "label": f"[{p.sku}] {p.name}",
        "category_id": p.category_id,
        "category": p.category.name if p.category else None,
        "uom": p.uom,
        "unit_cost": p.unit_cost,
        "reorder_min": p.reorder_min,
        "reorder_qty": p.reorder_qty,
        "on_hand": on_hand,
        "low_stock": on_hand <= p.reorder_min,
    }


@router.get("/categories")
def list_categories(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"id": c.id, "name": c.name} for c in db.scalars(select(Category).order_by(Category.name))]


@router.post("/categories", status_code=201)
def create_category(body: CategoryIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Name required")
    c = db.scalar(select(Category).where(func.lower(Category.name) == name.lower()))
    if not c:
        c = Category(name=name)
        db.add(c)
        db.commit()
    return {"id": c.id, "name": c.name}


@router.get("/products")
def list_products(
    q: str | None = None,
    category_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    stmt = select(Product).order_by(Product.name)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Product.name.ilike(like), Product.sku.ilike(like)))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    return [product_out(db, p) for p in db.scalars(stmt)]


@router.post("/products", status_code=201)
def create_product(body: ProductIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sku = body.sku.strip().upper()
    if not body.name.strip() or not sku:
        raise HTTPException(422, "Name and SKU are required")
    if db.scalar(select(Product).where(Product.sku == sku)):
        raise HTTPException(409, "SKU already exists")
    p = Product(
        name=body.name.strip(), sku=sku, category_id=body.category_id, uom=body.uom or "Unit",
        unit_cost=body.unit_cost, reorder_min=body.reorder_min, reorder_qty=body.reorder_qty,
    )
    db.add(p)
    db.flush()
    if body.initial_stock > 0:
        loc = db.get(Location, body.initial_location_id) if body.initial_location_id else db.scalar(
            select(Location).where(Location.type == "internal").order_by(Location.id)
        )
        if not loc or loc.type != "internal":
            raise HTTPException(422, "Choose a valid stock location for the initial stock")
        stock.adjust(db, p, loc, body.initial_stock, user.id)
    db.commit()
    return product_out(db, p)


@router.put("/products/{pid}")
def update_product(pid: int, body: ProductIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    p = db.get(Product, pid)
    if not p:
        raise HTTPException(404, "Product not found")
    sku = body.sku.strip().upper()
    if db.scalar(select(Product).where(Product.sku == sku, Product.id != pid)):
        raise HTTPException(409, "SKU already exists")
    p.name, p.sku, p.category_id, p.uom = body.name.strip(), sku, body.category_id, body.uom
    p.unit_cost, p.reorder_min, p.reorder_qty = body.unit_cost, body.reorder_min, body.reorder_qty
    db.commit()
    return product_out(db, p)
