import math
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from .. import audit, stock
from ..db import get_db
from ..deps import current_user, manager
from ..filters import op_filters
from ..models import Location, Operation, OperationLine, Product, StockQuant, User, Warehouse
from ..pagination import PageParams, count_rows, envelope, slice_stmt
from ..queries import cost_expr, incoming_map, internal_stock, reserved_map
from .operations import LineIn, _load, _make_lines, _resolve_locations, op_out

router = APIRouter(tags=["inventory"])


class AdjustIn(BaseModel):
    product_id: int
    location_id: int
    counted_qty: Annotated[float, Field(ge=0, le=1_000_000_000)]


# ------------------------------------------------------------------ stock by product and location
def stock_rows(db: Session, *, q=None, warehouse_id=None, category_id=None, page: PageParams | None = None):
    """Availability per product with its locations. A whole page costs four queries, however many products the catalogue has."""
    base = select(Product).where(Product.active.is_(True))
    if q:
        like = f"%{q}%"
        base = base.where(or_(Product.name.ilike(like), Product.sku.ilike(like)))
    if category_id:
        base = base.where(Product.category_id == category_id)
    stmt = base.options(joinedload(Product.category)).order_by(Product.name, Product.id)
    paged = page is not None and page.enabled
    products = list(db.scalars(slice_stmt(stmt, page) if paged else stmt))
    total = count_rows(db, base) if paged else len(products)
    ids = [p.id for p in products]

    by_product: dict[int, list] = {}
    if ids:
        qstmt = (
            select(StockQuant.product_id, StockQuant.location_id, StockQuant.quantity, Location.short_code, Warehouse.short_code)
            .join(Location, Location.id == StockQuant.location_id)
            .join(Warehouse, Warehouse.id == Location.warehouse_id)
            .where(Location.type == "internal", StockQuant.product_id.in_(ids))
            .order_by(StockQuant.product_id, StockQuant.location_id)
        )
        if warehouse_id:
            qstmt = qstmt.where(Location.warehouse_id == warehouse_id)
        for pid, lid, qty, loc_code, wh_code in db.execute(qstmt):
            by_product.setdefault(pid, []).append((lid, float(qty), f"{wh_code}/{loc_code}"))
    reserved = reserved_map(db, ids)

    rows = []
    for p in products:
        locs, total_qty, free_total = [], 0.0, 0.0
        for lid, qty, name in by_product.get(p.id, []):
            free = qty - reserved.get((p.id, lid), 0.0)
            locs.append({"location_id": lid, "location": name, "on_hand": qty, "free_to_use": free})
            total_qty += qty
            free_total += free
        rows.append({
            "product_id": p.id, "name": p.name, "sku": p.sku, "category": p.category.name if p.category else None,
            "unit_cost": p.unit_cost, "on_hand": total_qty, "free_to_use": free_total, "reorder_min": p.reorder_min,
            "low_stock": total_qty <= p.reorder_min, "locations": locs,
        })
    return envelope(rows, total, page) if paged else rows


@router.get("/stock")
def stock_list(
    q: str | None = None,
    warehouse_id: int | None = None,
    category_id: int | None = None,
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    return stock_rows(db, q=q, warehouse_id=warehouse_id, category_id=category_id, page=page)


@router.post("/stock/adjust")
def stock_adjust(body: AdjustIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Counting stock is warehouse work, so every role may do it. The difference is logged as an adjustment."""
    product, loc = db.get(Product, body.product_id), db.get(Location, body.location_id)
    if not product or not loc or loc.type != "internal":
        raise HTTPException(404, "Product or location not found")
    before = stock.on_hand(db, product.id, loc.id)
    op = stock.adjust(db, product, loc, body.counted_qty, user.id)
    audit.record(db, user, "adjust", "stock", product.id, f"{product.sku} @ {loc.full_name}",
                 changes={"on_hand": [before, body.counted_qty]}, detail=op.reference)
    db.commit()
    return {"reference": op.reference, "before": before, "after": body.counted_qty, "difference": body.counted_qty - before}


# ------------------------------------------------------------------ reordering
def suggested_qty(p: Product, on_hand: float, incoming: float) -> float:
    """Min/max style rule: when on hand + incoming falls to the reorder level, order the reorder
    quantity (in whole multiples if the shortfall is larger). No rule set means no suggestion."""
    if p.reorder_min <= 0 and p.reorder_qty <= 0:
        return 0
    effective = on_hand + incoming
    if effective > p.reorder_min:
        return 0
    need = p.reorder_min - effective
    if p.reorder_qty > 0:
        return p.reorder_qty * max(1, math.ceil(need / p.reorder_qty))
    return max(need, 1)


def _incoming_sub(warehouse_id: int | None):
    stmt = (
        select(OperationLine.product_id.label("product_id"), func.sum(OperationLine.quantity).label("inc"))
        .join(Operation, Operation.id == OperationLine.operation_id)
        .where(Operation.type == "IN", Operation.status.in_(["draft", "waiting", "ready"]))
        .group_by(OperationLine.product_id)
    )
    if warehouse_id:
        stmt = stmt.where(Operation.warehouse_id == warehouse_id)
    return stmt.subquery()


def _reorder_stmt(warehouse_id: int | None, location_id: int | None = None, category_id: int | None = None):
    """Products with a reorder rule whose stock plus incoming has fallen to the level, computed in the database."""
    tot = internal_stock(warehouse_id, location_id).subquery()
    inc = _incoming_sub(warehouse_id)
    on_hand = func.coalesce(tot.c.qty, 0)
    incoming = func.coalesce(inc.c.inc, 0)
    stmt = (
        select(Product, on_hand.label("qty"), incoming.label("incoming"))
        .outerjoin(tot, tot.c.product_id == Product.id)
        .outerjoin(inc, inc.c.product_id == Product.id)
        .where(
            Product.active.is_(True),
            or_(Product.reorder_min > 0, Product.reorder_qty > 0),
            on_hand + incoming <= Product.reorder_min,
        )
    )
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    return stmt


def _suggestions(db: Session, warehouse_id: int | None) -> list[dict]:
    out = []
    for p, qty, incoming in db.execute(_reorder_stmt(warehouse_id).order_by(Product.name)):
        qty, incoming = float(qty), float(incoming)
        want = suggested_qty(p, qty, incoming)
        if want > 0:
            out.append({
                "product_id": p.id, "name": p.name, "sku": p.sku, "on_hand": qty, "incoming": incoming,
                "reorder_min": p.reorder_min, "reorder_qty": p.reorder_qty, "suggested_qty": want, "unit_cost": p.unit_cost,
            })
    return out


class ReorderIn(BaseModel):
    product_ids: list[int] | None = Field(default=None, max_length=500)
    warehouse_id: int | None = None


@router.get("/reorder/suggestions")
def reorder_suggestions(
    warehouse_id: int | None = None, page: PageParams = Depends(), db: Session = Depends(get_db), _: User = Depends(current_user)
):
    items = _suggestions(db, warehouse_id)
    if not page.enabled:
        return items
    return envelope(items[page.offset:page.offset + page.size], len(items), page)


@router.post("/reorder/receipt", status_code=201)
def reorder_receipt(body: ReorderIn, db: Session = Depends(get_db), user: User = Depends(manager)):
    """Create one draft receipt covering the suggested quantities (all, or just the chosen products)."""
    items = _suggestions(db, body.warehouse_id)
    if body.product_ids is not None:
        items = [i for i in items if i["product_id"] in body.product_ids]
    if not items:
        raise HTTPException(422, "Nothing needs reordering right now")
    wh, src, dst = _resolve_locations(db, "IN", body.warehouse_id, None, None)
    op = Operation(
        reference=stock.next_reference(db, wh, "IN"), type="IN", status="draft", contact=None,
        schedule_date=date.today(), responsible_id=user.id, warehouse_id=wh.id,
        source_location_id=src.id, dest_location_id=dst.id,
    )
    op.lines = _make_lines(db, [LineIn(product_id=i["product_id"], quantity=i["suggested_qty"]) for i in items], "IN")
    db.add(op)
    db.flush()
    audit.record(db, user, "reorder", "operation", op.id, op.reference, detail=f"{len(items)} product(s) from reorder suggestions")
    db.commit()
    return op_out(db, _load(db, op.id))


# ------------------------------------------------------------------ dashboard
CARD_TYPES = ["IN", "OUT", "INT", "ADJ"]
ALL_STATUSES = ["draft", "waiting", "ready", "done", "cancelled"]
OPEN_STATES = ("draft", "waiting", "ready")


@router.get("/dashboard")
def dashboard(
    doc_type: str | None = None,
    status: str | None = None,
    warehouse_id: int | None = None,
    location_id: int | None = None,
    category_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    """doc_type / status shape the operation cards; warehouse, location and category shape everything.
    Everything is counted in the database: two grouped queries for documents, two for stock."""
    today = date.today()

    # -- documents: one grouped query, then the cards are assembled from a handful of rows
    doc_rows = db.execute(
        op_filters(
            select(
                Operation.type, Operation.status, func.count(),
                func.count().filter(Operation.schedule_date < today), func.count().filter(Operation.schedule_date > today),
            ).group_by(Operation.type, Operation.status),
            warehouse_id=warehouse_id, location_id=location_id, category_id=category_id,
        )
    ).all()
    grid = {(t, s): (n, past, future) for t, s, n, past, future in doc_rows}

    def card(op_type: str, use_status: bool = True) -> dict:
        if use_status and status:
            chosen = [status]
        else:
            chosen = ALL_STATUSES if op_type == "ADJ" and use_status else list(OPEN_STATES)
        cell = lambda s, i: grid.get((op_type, s), (0, 0, 0))[i]  # noqa: E731
        return {
            "type": op_type,
            "to_process": sum(cell(s, 0) for s in chosen),
            "late": sum(cell(s, 1) for s in chosen if s in OPEN_STATES),
            "waiting": cell("waiting", 0) if "waiting" in chosen else 0,
            "operations": sum(cell(s, 2) for s in chosen),
            "by_status": {k: (cell(k, 0) if k in chosen else 0) for k in ALL_STATUSES},
        }

    shown = [doc_type] if doc_type in CARD_TYPES else CARD_TYPES[:3]
    pending = {t: card(t, use_status=False)["to_process"] for t in ("IN", "OUT", "INT")}

    # -- stock: counts and value straight from SQL, plus the ten worst rows
    tot = internal_stock(warehouse_id, location_id).subquery()
    qty = func.coalesce(tot.c.qty, 0)
    scope = [Product.active.is_(True)] + ([Product.category_id == category_id] if category_id else [])
    in_stock, out_of_stock, value, low_in_stock = db.execute(
        select(
            func.count().filter(qty > 0),
            func.count().filter(qty <= 0),
            func.coalesce(func.sum(case((qty > 0, qty * cost_expr()), else_=0)), 0),
            func.count().filter(and_(qty > 0, qty <= Product.reorder_min)),
        ).select_from(Product).outerjoin(tot, tot.c.product_id == Product.id).where(*scope)
    ).one()

    worst = db.execute(
        select(Product, qty.label("qty")).outerjoin(tot, tot.c.product_id == Product.id)
        .where(*scope, qty <= Product.reorder_min).order_by(qty, Product.name).limit(10)
    ).all()
    incoming = incoming_map(db, warehouse_id, [p.id for p, _ in worst])
    low_items = [
        {"product_id": p.id, "name": p.name, "sku": p.sku, "on_hand": float(q), "reorder_min": p.reorder_min,
         "incoming": incoming.get(p.id, 0), "suggested_qty": suggested_qty(p, float(q), incoming.get(p.id, 0))}
        for p, q in worst
    ]
    reorder_count = count_rows(db, _reorder_stmt(warehouse_id, location_id, category_id))

    return {
        "cards": [card(t) for t in shown],
        "kpis": {
            "total_products_in_stock": in_stock,
            "stock_value": round(float(value), 2),
            "low_stock": low_in_stock,
            "out_of_stock": out_of_stock,
            "pending_receipts": pending["IN"],
            "pending_deliveries": pending["OUT"],
            "internal_transfers_scheduled": pending["INT"],
        },
        "low_stock_items": low_items,
        "reorder_count": reorder_count,
    }
