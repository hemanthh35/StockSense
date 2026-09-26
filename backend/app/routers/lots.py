from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import lots
from ..db import get_db
from ..deps import current_user
from ..models import Product, StockLot, User
from ..pagination import PageParams, count_rows, envelope, slice_stmt
from ..queries import cost_expr

router = APIRouter(tags=["lots"])


def lots_page(db: Session, *, days: int = 30, status: str | None = None, q: str | None = None, page: PageParams | None = None):
    today, soon = date.today(), date.today() + timedelta(days=days)
    base = select(StockLot, Product, cost_expr()).join(Product, Product.id == StockLot.product_id).where(StockLot.remaining_qty > 0)
    if q:
        like = f"%{q}%"
        base = base.where(or_(Product.name.ilike(like), Product.sku.ilike(like), StockLot.lot_no.ilike(like)))
    if status == "expired":
        base = base.where(StockLot.expiry_date < today)
    elif status == "soon":
        base = base.where(StockLot.expiry_date >= today, StockLot.expiry_date <= soon)
    elif status == "ok":
        base = base.where(StockLot.expiry_date > soon)
    elif status == "none":
        base = base.where(StockLot.expiry_date.is_(None))
    stmt = base.order_by(StockLot.expiry_date.asc().nulls_last(), Product.name, StockLot.id)
    paged = page is not None and page.enabled
    total = count_rows(db, base) if paged else 0
    out = []
    for lot, p, cost in db.execute(slice_stmt(stmt, page) if paged else stmt):
        left = (lot.expiry_date - today).days if lot.expiry_date else None
        out.append({
            "id": lot.id, "product_id": p.id, "sku": p.sku, "name": p.name, "lot_no": lot.lot_no,
            "expiry_date": lot.expiry_date.isoformat() if lot.expiry_date else None, "days_left": left,
            "level": "none" if left is None else "expired" if left < 0 else "soon" if left <= days else "ok",
            "remaining": float(lot.remaining_qty), "received": float(lot.received_qty), "received_on": lot.received_on.isoformat() if lot.received_on else None,
            "source": lot.source_ref, "value": round(float(lot.remaining_qty) * float(cost or 0), 2),
        })
    return envelope(out, total, page) if paged else out


@router.get("/lots")
def list_lots(
    days: int = 30, status: str | None = None, q: str | None = None,
    page: PageParams = Depends(), db: Session = Depends(get_db), _: User = Depends(current_user),
):
    """Batches still in stock, earliest expiry first. status: expired | soon | ok | none."""
    days = max(1, min(days, 365))
    data = lots_page(db, days=days, status=status, q=q, page=page)
    summary = lots.summary(db, days)
    return {**data, "summary": summary} if isinstance(data, dict) else {"rows": data, "summary": summary}
