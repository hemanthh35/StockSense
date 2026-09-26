from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import stock
from ..db import get_db
from ..deps import current_user
from ..filters import op_filters
from ..models import Location, Operation, Product, StockQuant, User

router = APIRouter(tags=["inventory"])


class AdjustIn(BaseModel):
    product_id: int
    location_id: int
    counted_qty: float


def _internal_quants(db: Session, warehouse_id: int | None, location_id: int | None = None):
    stmt = select(StockQuant, Location).join(Location, Location.id == StockQuant.location_id).where(
        Location.type == "internal"
    )
    if warehouse_id:
        stmt = stmt.where(Location.warehouse_id == warehouse_id)
    if location_id:
        stmt = stmt.where(Location.id == location_id)
    return db.execute(stmt).all()


@router.get("/stock")
def stock_list(
    q: str | None = None,
    warehouse_id: int | None = None,
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
    by_product: dict[int, list] = {}
    for quant, loc in _internal_quants(db, warehouse_id):
        by_product.setdefault(quant.product_id, []).append((quant, loc))
    rows = []
    for p in db.scalars(stmt):
        locs, total, free = [], 0.0, 0.0
        for quant, loc in by_product.get(p.id, []):
            f = stock.free_to_use(db, p.id, loc.id)
            locs.append({"location_id": loc.id, "location": loc.full_name, "on_hand": quant.quantity, "free_to_use": f})
            total += quant.quantity
            free += f
        rows.append(
            {
                "product_id": p.id,
                "name": p.name,
                "sku": p.sku,
                "category": p.category.name if p.category else None,
                "unit_cost": p.unit_cost,
                "on_hand": total,
                "free_to_use": free,
                "reorder_min": p.reorder_min,
                "low_stock": total <= p.reorder_min,
                "locations": locs,
            }
        )
    return rows


@router.post("/stock/adjust")
def stock_adjust(body: AdjustIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.counted_qty < 0:
        raise HTTPException(422, "Counted quantity cannot be negative")
    product, loc = db.get(Product, body.product_id), db.get(Location, body.location_id)
    if not product or not loc or loc.type != "internal":
        raise HTTPException(404, "Product or location not found")
    before = stock.on_hand(db, product.id, loc.id)
    op = stock.adjust(db, product, loc, body.counted_qty, user.id)
    db.commit()
    return {"reference": op.reference, "before": before, "after": body.counted_qty, "difference": body.counted_qty - before}


CARD_TYPES = ["IN", "OUT", "INT", "ADJ"]
ALL_STATUSES = ["draft", "waiting", "ready", "done", "cancelled"]


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
    """doc_type / status shape the operation cards; warehouse, location and category shape everything."""
    today = date.today()
    scope = dict(warehouse_id=warehouse_id, location_id=location_id, category_id=category_id)

    def card(op_type: str, with_status: bool = True) -> dict:
        stmt = op_filters(select(Operation), type=op_type, status=status if with_status else None, **scope)
        if not (with_status and status) and op_type != "ADJ":
            stmt = stmt.where(Operation.status.notin_(["done", "cancelled"]))  # default view = open work
        ops = list(db.scalars(stmt))
        return {
            "type": op_type,
            "to_process": len(ops),
            "late": sum(1 for o in ops if o.schedule_date and o.schedule_date < today and o.status not in ("done", "cancelled")),
            "waiting": sum(1 for o in ops if o.status == "waiting"),
            "operations": sum(1 for o in ops if o.schedule_date and o.schedule_date > today),
            "by_status": {k: sum(1 for o in ops if o.status == k) for k in ALL_STATUSES},
        }

    shown = [doc_type] if doc_type in CARD_TYPES else CARD_TYPES[:3]

    totals: dict[int, float] = {}
    for quant, _loc in _internal_quants(db, warehouse_id, location_id):
        totals[quant.product_id] = totals.get(quant.product_id, 0) + quant.quantity
    pstmt = select(Product)
    if category_id:
        pstmt = pstmt.where(Product.category_id == category_id)
    low = []
    out_of_stock = in_stock = 0
    for p in db.scalars(pstmt):
        qty = totals.get(p.id, 0)
        if qty > 0:
            in_stock += 1
        else:
            out_of_stock += 1
        if qty <= p.reorder_min:
            low.append({"product_id": p.id, "name": p.name, "sku": p.sku, "on_hand": qty, "reorder_min": p.reorder_min})

    pending = {t: card(t, with_status=False)["to_process"] for t in ("IN", "OUT", "INT")}
    return {
        "cards": [card(t) for t in shown],
        "kpis": {
            "total_products_in_stock": in_stock,
            "low_stock": len(low) - out_of_stock,
            "out_of_stock": out_of_stock,
            "pending_receipts": pending["IN"],
            "pending_deliveries": pending["OUT"],
            "internal_transfers_scheduled": pending["INT"],
        },
        "low_stock_items": sorted(low, key=lambda x: x["on_hand"])[:10],
    }
