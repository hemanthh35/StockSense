from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from .. import audit, lifecycle, pricing, stock
from ..conflict import bump, check_version
from ..db import get_db
from ..deps import current_user, manager
from ..models import Category, Location, Product, StockQuant, Tax, User
from ..pagination import PageParams, count_rows, envelope, slice_stmt
from ..queries import on_hand_map

router = APIRouter(tags=["products"])

Money = Annotated[float, Field(ge=0, le=1_000_000_000)]
Qty = Annotated[float, Field(ge=0, le=1_000_000_000)]

TRACKED = ["name", "sku", "category_id", "uom", "unit_cost", "cost_price", "reorder_min", "reorder_qty", "hsn_code", "tax_id"]


class CategoryIn(BaseModel):
    name: str = Field(max_length=100)


class ProductIn(BaseModel):
    name: str = Field(max_length=150)
    sku: str = Field(max_length=50)
    category_id: int | None = None
    uom: str = Field(default="Unit", max_length=20)
    unit_cost: Money = 0
    cost_price: Money = 0  # purchase price; 0 = same as unit_cost
    reorder_min: Qty = 0
    reorder_qty: Qty = 0
    hsn_code: str | None = Field(default=None, max_length=20)
    tax_id: int | None = None  # None = auto (category default, then global default); 0 = no tax
    initial_stock: Qty = 0
    initial_location_id: int | None = None
    version: int | None = None  # the version the editor loaded, for optimistic locking


def product_out(db: Session, p: Product, on_hand: float | None = None) -> dict:
    if on_hand is None:
        on_hand = on_hand_map(db, [p.id]).get(p.id, 0.0)
    return {
        "id": p.id,
        "name": p.name,
        "sku": p.sku,
        "label": f"[{p.sku}] {p.name}",
        "category_id": p.category_id,
        "category": p.category.name if p.category else None,
        "uom": p.uom,
        "unit_cost": p.unit_cost,
        "cost_price": p.cost_price,
        "avg_cost": p.avg_cost,
        "reorder_min": p.reorder_min,
        "reorder_qty": p.reorder_qty,
        "hsn_code": p.hsn_code,
        "tax_id": p.tax_id,
        "tax": {"id": p.tax.id, "name": p.tax.name, "rate": p.tax.rate} if p.tax else None,
        "active": p.active,
        "version": p.version,
        "on_hand": on_hand,
        "low_stock": on_hand <= p.reorder_min,
    }


def products_out(db: Session, products: list[Product]) -> list[dict]:
    """Serialise many products with ONE stock query (not one per product)."""
    stock_by_product = on_hand_map(db, [p.id for p in products])
    return [product_out(db, p, stock_by_product.get(p.id, 0.0)) for p in products]


def total_qty_zero(db: Session, p: Product) -> bool:
    return stock.total_on_hand(db, p.id) <= 0


def _resolve_tax_id(db: Session, body: ProductIn) -> int | None:
    if body.tax_id == 0:
        return None
    if body.tax_id:
        if not db.get(Tax, body.tax_id):
            raise HTTPException(422, "Unknown tax")
        return body.tax_id
    auto = pricing.auto_tax(db, body.category_id)
    return auto.id if auto else None


# ---------------------------------------------------------------- categories
def _category_out(c: Category, count: int = 0) -> dict:
    return {"id": c.id, "name": c.name, "default_tax_id": c.default_tax_id, "products": count}


@router.get("/categories")
def list_categories(db: Session = Depends(get_db), _: User = Depends(current_user)):
    counts = dict(db.execute(select(Product.category_id, func.count()).group_by(Product.category_id)).all())
    return [_category_out(c, counts.get(c.id, 0)) for c in db.scalars(select(Category).order_by(Category.name))]


@router.post("/categories", status_code=201)
def create_category(body: CategoryIn, db: Session = Depends(get_db), actor: User = Depends(manager)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Name required")
    c = db.scalar(select(Category).where(func.lower(Category.name) == name.lower()))
    if not c:
        c = Category(name=name)
        db.add(c)
        db.flush()
        audit.record(db, actor, "create", "category", c.id, c.name)
        db.commit()
    return _category_out(c)


@router.put("/categories/{cid}")
def rename_category(cid: int, body: CategoryIn, db: Session = Depends(get_db), actor: User = Depends(manager)):
    c = db.get(Category, cid)
    if not c:
        raise HTTPException(404, "Category not found")
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Name required")
    clash = db.scalar(select(Category).where(func.lower(Category.name) == name.lower(), Category.id != cid))
    if clash:
        raise HTTPException(409, "A category with this name already exists")
    old = c.name
    c.name = name
    if old != name:
        audit.record(db, actor, "update", "category", c.id, name, changes={"name": [old, name]})
    db.commit()
    return _category_out(c)


@router.delete("/categories/{cid}")
def delete_category(cid: int, db: Session = Depends(get_db), actor: User = Depends(manager)):
    c = db.get(Category, cid)
    if not c:
        raise HTTPException(404, "Category not found")
    used = db.scalar(select(func.count()).select_from(Product).where(Product.category_id == cid)) or 0
    if used:
        raise HTTPException(409, f"{used} product{'s' if used > 1 else ''} still use this category - move them to another category first")
    audit.record(db, actor, "delete", "category", cid, c.name)
    db.delete(c)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- products
def product_query(q: str | None, category_id: int | None, include_archived: bool, ids: str | None):
    stmt = select(Product)
    if not include_archived:
        stmt = stmt.where(Product.active.is_(True))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Product.name.ilike(like), Product.sku.ilike(like)))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if ids:
        try:
            id_list = [int(x) for x in ids.split(",") if x.strip()][:200]
        except ValueError:
            raise HTTPException(422, "ids must be a comma-separated list of numbers")
        stmt = stmt.where(Product.id.in_(id_list))
    return stmt


@router.get("/products")
def list_products(
    q: str | None = None,
    category_id: int | None = None,
    include_archived: bool = False,
    ids: str | None = None,
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    base = product_query(q, category_id, include_archived, ids)
    stmt = base.options(joinedload(Product.category), joinedload(Product.tax)).order_by(Product.name, Product.id)
    if not page.enabled:
        return products_out(db, list(db.scalars(stmt)))
    total = count_rows(db, base)
    return envelope(products_out(db, list(db.scalars(slice_stmt(stmt, page)))), total, page)


@router.post("/products", status_code=201)
def create_product(body: ProductIn, db: Session = Depends(get_db), user: User = Depends(manager)):
    sku = body.sku.strip().upper()
    if not body.name.strip() or not sku:
        raise HTTPException(422, "Name and SKU are required")
    if db.scalar(select(Product).where(Product.sku == sku)):
        raise HTTPException(409, "SKU already exists")
    p = Product(
        name=body.name.strip(), sku=sku, category_id=body.category_id, uom=body.uom or "Unit",
        unit_cost=body.unit_cost, cost_price=body.cost_price, avg_cost=body.cost_price or body.unit_cost,
        reorder_min=body.reorder_min, reorder_qty=body.reorder_qty,
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
    audit.record(db, user, "create", "product", p.id, f"{p.sku} · {p.name}")
    db.commit()
    return product_out(db, p)


def _get(db: Session, pid: int) -> Product:
    p = db.get(Product, pid)
    if not p:
        raise HTTPException(404, "Product not found")
    return p


@router.put("/products/{pid}")
def update_product(pid: int, body: ProductIn, db: Session = Depends(get_db), actor: User = Depends(manager)):
    p = _get(db, pid)
    check_version(p, body.version)
    sku = body.sku.strip().upper()
    if db.scalar(select(Product).where(Product.sku == sku, Product.id != pid)):
        raise HTTPException(409, "SKU already exists")
    old = audit.snapshot(p, TRACKED)
    p.name, p.sku, p.category_id, p.uom = body.name.strip(), sku, body.category_id, body.uom
    p.unit_cost, p.reorder_min, p.reorder_qty = body.unit_cost, body.reorder_min, body.reorder_qty
    p.cost_price = body.cost_price
    if total_qty_zero(db, p):
        p.avg_cost = body.cost_price or body.unit_cost  # nothing on the shelf, so re-base the average
    p.hsn_code = (body.hsn_code or "").strip() or None
    p.tax_id = _resolve_tax_id(db, body)
    if changes := audit.diff(old, audit.snapshot(p, TRACKED)):
        bump(p)
        audit.record(db, actor, "update", "product", p.id, f"{p.sku} · {p.name}", changes=changes)
    db.commit()
    return product_out(db, p)


@router.post("/products/{pid}/archive")
def archive_product(pid: int, db: Session = Depends(get_db), actor: User = Depends(manager)):
    p = _get(db, pid)
    if reason := lifecycle.archive_blocker(lifecycle.product_usage(db, pid), "This product"):
        raise HTTPException(409, reason)
    p.active = False
    bump(p)
    audit.record(db, actor, "archive", "product", p.id, f"{p.sku} · {p.name}")
    db.commit()
    return product_out(db, p)


@router.post("/products/{pid}/restore")
def restore_product(pid: int, db: Session = Depends(get_db), actor: User = Depends(manager)):
    p = _get(db, pid)
    p.active = True
    bump(p)
    audit.record(db, actor, "restore", "product", p.id, f"{p.sku} · {p.name}")
    db.commit()
    return product_out(db, p)


@router.delete("/products/{pid}")
def delete_product(pid: int, db: Session = Depends(get_db), actor: User = Depends(manager)):
    p = _get(db, pid)
    if reason := lifecycle.delete_blocker(lifecycle.product_usage(db, pid), "This product"):
        raise HTTPException(409, reason)
    label = f"{p.sku} · {p.name}"
    db.query(StockQuant).filter(StockQuant.product_id == pid).delete()
    db.delete(p)
    audit.record(db, actor, "delete", "product", pid, label)
    db.commit()
    return {"ok": True}
