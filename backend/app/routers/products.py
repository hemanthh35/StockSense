from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import lifecycle, pricing, stock
from ..db import get_db
from ..deps import current_user
from ..models import Category, Location, Product, StockQuant, Tax, User

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
    hsn_code: str | None = None
    tax_id: int | None = None  # None = auto (category default, then global default); 0 = no tax
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
        "hsn_code": p.hsn_code,
        "tax_id": p.tax_id,
        "tax": {"id": p.tax.id, "name": p.tax.name, "rate": p.tax.rate} if p.tax else None,
        "active": p.active,
        "on_hand": on_hand,
        "low_stock": on_hand <= p.reorder_min,
    }


def _resolve_tax_id(db: Session, body: ProductIn) -> int | None:
    if body.tax_id == 0:
        return None
    if body.tax_id:
        if not db.get(Tax, body.tax_id):
            raise HTTPException(422, "Unknown tax")
        return body.tax_id
    auto = pricing.auto_tax(db, body.category_id)
    return auto.id if auto else None


def _category_out(c: Category, count: int = 0) -> dict:
    return {"id": c.id, "name": c.name, "default_tax_id": c.default_tax_id, "products": count}


@router.get("/categories")
def list_categories(db: Session = Depends(get_db), _: User = Depends(current_user)):
    counts = dict(db.execute(select(Product.category_id, func.count()).group_by(Product.category_id)).all())
    return [_category_out(c, counts.get(c.id, 0)) for c in db.scalars(select(Category).order_by(Category.name))]


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
    return _category_out(c)


@router.put("/categories/{cid}")
def rename_category(cid: int, body: CategoryIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    c = db.get(Category, cid)
    if not c:
        raise HTTPException(404, "Category not found")
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Name required")
    clash = db.scalar(select(Category).where(func.lower(Category.name) == name.lower(), Category.id != cid))
    if clash:
        raise HTTPException(409, "A category with this name already exists")
    c.name = name
    db.commit()
    return _category_out(c)


@router.delete("/categories/{cid}")
def delete_category(cid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    c = db.get(Category, cid)
    if not c:
        raise HTTPException(404, "Category not found")
    used = db.scalar(select(func.count()).select_from(Product).where(Product.category_id == cid)) or 0
    if used:
        raise HTTPException(409, f"{used} product{'s' if used > 1 else ''} still use this category - move them to another category first")
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.get("/products")
def list_products(
    q: str | None = None,
    category_id: int | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    stmt = select(Product).order_by(Product.name)
    if not include_archived:
        stmt = stmt.where(Product.active.is_(True))
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
        hsn_code=(body.hsn_code or "").strip() or None, tax_id=_resolve_tax_id(db, body),
    )
    db.add(p)
    db.flush()
    if body.initial_stock > 0:
        loc = db.get(Location, body.initial_location_id) if body.initial_location_id else db.scalar(
            select(Location).where(Location.type == "internal", Location.active.is_(True)).order_by(Location.id)
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
    p.hsn_code = (body.hsn_code or "").strip() or None
    p.tax_id = _resolve_tax_id(db, body)
    db.commit()
    return product_out(db, p)


def _get_product(db: Session, pid: int) -> Product:
    p = db.get(Product, pid)
    if not p:
        raise HTTPException(404, "Product not found")
    return p


@router.post("/products/{pid}/archive")
def archive_product(pid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    p = _get_product(db, pid)
    if reason := lifecycle.archive_blocker(lifecycle.product_usage(db, pid), "This product"):
        raise HTTPException(409, reason)
    p.active = False
    db.commit()
    return product_out(db, p)


@router.post("/products/{pid}/restore")
def restore_product(pid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    p = _get_product(db, pid)
    p.active = True
    db.commit()
    return product_out(db, p)


@router.delete("/products/{pid}")
def delete_product(pid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    p = _get_product(db, pid)
    if reason := lifecycle.delete_blocker(lifecycle.product_usage(db, pid), "This product"):
        raise HTTPException(409, reason)
    db.query(StockQuant).filter(StockQuant.product_id == pid).delete()
    db.delete(p)
    db.commit()
    return {"ok": True}
