"""Stock valuation (weighted average cost) and delivery margin, computed with grouped SQL and paged in the database."""
import math
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..deps import current_user
from ..filters import op_filters
from ..models import Category, Operation, OperationLine, Product, User
from ..pagination import PageParams
from ..queries import cost_expr, incoming_map, internal_stock, on_hand_map
from ..stock import utcnow

router = APIRouter(tags=["reports"])


def _with_paging(report: dict, total: int, page: PageParams | None) -> dict:
    if page is not None and page.enabled:
        report.update({"items": report["rows"], "total": total, "page": page.page, "page_size": page.size,
                       "pages": max(1, math.ceil(total / page.size))})
    return report


def valuation_rows(
    db: Session, q: str | None, warehouse_id: int | None, location_id: int | None, category_id: int | None,
    include_zero: bool, page: PageParams | None = None,
) -> dict:
    tot = internal_stock(warehouse_id, location_id).subquery()
    qty = func.coalesce(tot.c.qty, 0)
    cost = cost_expr()
    conds = [Product.active.is_(True)]
    if category_id:
        conds.append(Product.category_id == category_id)
    if q:
        like = f"%{q}%"
        conds.append(or_(Product.name.ilike(like), Product.sku.ilike(like)))
    if not include_zero:
        conds.append(qty > 0)

    value, retail = qty * cost, qty * Product.unit_cost
    from_ = Product.__table__.outerjoin(tot, tot.c.product_id == Product.id)

    stmt = (
        select(Product, qty.label("qty"), value.label("value"), retail.label("retail"))
        .select_from(from_).options(joinedload(Product.category)).where(*conds).order_by(desc("value"), Product.name)
    )
    total_rows = db.scalar(select(func.count()).select_from(from_).where(*conds)) or 0
    if page is not None and page.enabled:
        stmt = stmt.limit(page.size).offset(page.offset)
    rows = [
        {
            "product_id": p.id, "sku": p.sku, "name": p.name, "category": p.category.name if p.category else None,
            "on_hand": float(q_), "avg_cost": round(float(p.avg_cost or p.cost_price or p.unit_cost), 4),
            "value": round(float(v), 2), "sales_price": p.unit_cost, "retail_value": round(float(r), 2),
        }
        for p, q_, v, r in db.execute(stmt)
    ]

    sums = db.execute(select(func.coalesce(func.sum(qty), 0), func.coalesce(func.sum(value), 0), func.coalesce(func.sum(retail), 0)).select_from(from_).where(*conds)).one()
    by_cat = db.execute(
        select(func.coalesce(Category.name, "Uncategorised"), func.sum(value).label("v"))
        .select_from(from_.outerjoin(Category, Category.id == Product.category_id))
        .where(*conds).group_by(Category.name).order_by(desc("v"))
    ).all()
    total_value, total_retail = round(float(sums[1]), 2), round(float(sums[2]), 2)
    report = {
        "rows": rows,
        "totals": {"on_hand": float(sums[0]), "value": total_value, "retail_value": total_retail,
                   "potential_margin": round(total_retail - total_value, 2)},
        "by_category": [{"category": name, "value": round(float(v), 2)} for name, v in by_cat],
    }
    return _with_paging(report, total_rows, page)


@router.get("/reports/valuation")
def valuation(
    q: str | None = None,
    warehouse_id: int | None = None,
    location_id: int | None = None,
    category_id: int | None = None,
    include_zero: bool = False,
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    """What the stock on the shelves is worth at weighted-average purchase cost."""
    return valuation_rows(db, q, warehouse_id, location_id, category_id, include_zero, page)


def margin_rows(db: Session, days: int, warehouse_id: int | None, category_id: int | None, page: PageParams | None = None) -> dict:
    since = utcnow() - timedelta(days=days)
    cost = func.coalesce(OperationLine.cost_price, cost_expr())
    quantity = func.sum(OperationLine.quantity)
    revenue = func.sum(OperationLine.quantity * OperationLine.unit_price)
    spent = func.sum(OperationLine.quantity * cost)

    def scoped(stmt):
        stmt = stmt.select_from(Operation).join(OperationLine, OperationLine.operation_id == Operation.id).join(
            Product, Product.id == OperationLine.product_id
        ).where(Operation.type == "OUT", Operation.status == "done", Operation.done_at >= since)
        stmt = op_filters(stmt, warehouse_id=warehouse_id)
        return stmt.where(Product.category_id == category_id) if category_id else stmt

    grouped = scoped(select(Product.id, Product.sku, Product.name, quantity, revenue, spent)).group_by(Product.id, Product.sku, Product.name)
    total_rows = db.scalar(select(func.count()).select_from(grouped.subquery())) or 0
    stmt = grouped.order_by((revenue - spent).desc(), Product.name)
    if page is not None and page.enabled:
        stmt = stmt.limit(page.size).offset(page.offset)
    rows = []
    for pid, sku, name, qty_, rev_, cost_ in db.execute(stmt):
        rev_, cost_ = round(float(rev_), 2), round(float(cost_), 2)
        margin_ = round(rev_ - cost_, 2)
        rows.append({"product_id": pid, "sku": sku, "name": name, "quantity": float(qty_), "revenue": rev_, "cost": cost_,
                     "margin": margin_, "margin_pct": round(margin_ / rev_ * 100, 1) if rev_ else 0})
    t_rev, t_cost = db.execute(scoped(select(func.coalesce(func.sum(OperationLine.quantity * OperationLine.unit_price), 0),
                                              func.coalesce(func.sum(OperationLine.quantity * cost), 0)))).one()
    t_rev, t_cost = round(float(t_rev), 2), round(float(t_cost), 2)
    report = {
        "days": days,
        "rows": rows,
        "totals": {"revenue": t_rev, "cost": t_cost, "margin": round(t_rev - t_cost, 2),
                   "margin_pct": round((t_rev - t_cost) / t_rev * 100, 1) if t_rev else 0},
    }
    return _with_paging(report, total_rows, page)


@router.get("/reports/margin")
def margin(
    days: int = 30,
    warehouse_id: int | None = None,
    category_id: int | None = None,
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    """Revenue (before tax) against average cost for deliveries validated in the last `days` days."""
    return margin_rows(db, max(1, min(days, 3650)), warehouse_id, category_id, page)


# ------------------------------------------------------------------ forecast
def forecast_rows(db: Session, days: int, warehouse_id: int | None = None, page: PageParams | None = None, level: str | None = None) -> dict:
    """Days of stock left per product, from what was delivered over the last `days` days. Products nobody bought are left out."""
    since = utcnow() - timedelta(days=days)
    sold = (
        select(OperationLine.product_id, func.sum(OperationLine.quantity))
        .join(Operation, Operation.id == OperationLine.operation_id)
        .where(Operation.type == "OUT", Operation.status == "done", Operation.done_at >= since)
        .group_by(OperationLine.product_id)
    )
    if warehouse_id:
        sold = sold.where(Operation.warehouse_id == warehouse_id)
    sold_by = {pid: float(q or 0) for pid, q in db.execute(sold).all() if q and q > 0}
    ids = list(sold_by)
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids), Product.active.is_(True)))} if ids else {}
    have = on_hand_map(db, list(products), warehouse_id)
    coming = incoming_map(db, warehouse_id, list(products))
    today = utcnow().date()
    rows = []
    for pid, p in products.items():
        qty, per_day = have.get(pid, 0.0), sold_by[pid] / days
        left = qty / per_day if per_day else None
        level = "out" if qty <= 0 else "critical" if left < 7 else "soon" if left < 14 else "ok"
        rows.append({
            "product_id": pid, "sku": p.sku, "name": p.name, "on_hand": qty, "incoming": coming.get(pid, 0.0),
            "sold": sold_by[pid], "per_day": round(per_day, 2), "days_left": round(left, 1),
            "runs_out_on": (today + timedelta(days=int(left))).isoformat() if qty > 0 else None,
            "level": level, "reorder_min": p.reorder_min,
        })
    rows.sort(key=lambda r: (r["days_left"], r["name"]))
    counts = {k: sum(1 for r in rows if r["level"] == k) for k in ("out", "critical", "soon", "ok")}
    if level:
        rows = [r for r in rows if r["level"] == level]
    report = {"days": days, "rows": rows, "counts": counts}
    if page is not None and page.enabled:
        report.update({"rows": rows[page.offset:page.offset + page.size], "items": rows[page.offset:page.offset + page.size],
                       "total": len(rows), "page": page.page, "page_size": page.size, "pages": max(1, math.ceil(len(rows) / page.size))})
    return report


@router.get("/reports/forecast")
def forecast(
    days: int = 30,
    warehouse_id: int | None = None,
    level: str | None = None,
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    """How long the stock will last at the recent pace of deliveries, soonest to run out first."""
    return forecast_rows(db, max(7, min(days, 365)), warehouse_id, page, level)
