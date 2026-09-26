"""Stock valuation (weighted average cost) and delivery margin."""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import current_user
from ..filters import op_filters
from ..models import Operation, Product, User
from ..stock import utcnow
from .inventory import _internal_quants

router = APIRouter(tags=["reports"])


def valuation_rows(
    db: Session, q: str | None, warehouse_id: int | None, location_id: int | None, category_id: int | None, include_zero: bool
) -> dict:
    totals: dict[int, float] = {}
    for quant, _loc in _internal_quants(db, warehouse_id, location_id):
        totals[quant.product_id] = totals.get(quant.product_id, 0) + quant.quantity

    stmt = select(Product).where(Product.active.is_(True)).order_by(Product.name)
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    needle = (q or "").lower()
    rows = []
    for p in db.scalars(stmt):
        qty = totals.get(p.id, 0)
        if needle and needle not in p.name.lower() and needle not in p.sku.lower():
            continue
        if qty <= 0 and not include_zero:
            continue
        cost = p.avg_cost or p.cost_price or p.unit_cost
        rows.append({
            "product_id": p.id, "sku": p.sku, "name": p.name, "category": p.category.name if p.category else None,
            "on_hand": qty, "avg_cost": round(cost, 4), "value": round(qty * cost, 2),
            "sales_price": p.unit_cost, "retail_value": round(qty * p.unit_cost, 2),
        })
    rows.sort(key=lambda r: r["value"], reverse=True)

    by_cat: dict[str, float] = {}
    for r in rows:
        by_cat[r["category"] or "Uncategorised"] = by_cat.get(r["category"] or "Uncategorised", 0) + r["value"]
    value = round(sum(r["value"] for r in rows), 2)
    retail = round(sum(r["retail_value"] for r in rows), 2)
    return {
        "rows": rows,
        "totals": {"on_hand": sum(r["on_hand"] for r in rows), "value": value, "retail_value": retail,
                   "potential_margin": round(retail - value, 2)},
        "by_category": [{"category": k, "value": round(v, 2)} for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])],
    }


@router.get("/reports/valuation")
def valuation(
    q: str | None = None,
    warehouse_id: int | None = None,
    location_id: int | None = None,
    category_id: int | None = None,
    include_zero: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    """What the stock on the shelves is worth at weighted-average purchase cost."""
    return valuation_rows(db, q, warehouse_id, location_id, category_id, include_zero)


def margin_rows(db: Session, days: int, warehouse_id: int | None, category_id: int | None) -> dict:
    since = utcnow() - timedelta(days=days)
    stmt = op_filters(
        select(Operation).options(selectinload(Operation.lines)),
        type="OUT", status="done", warehouse_id=warehouse_id,
    ).where(Operation.done_at >= since)
    per: dict[int, dict] = {}
    for op in db.scalars(stmt):
        for ln in op.lines:
            p = ln.product
            if category_id and p.category_id != category_id:
                continue
            row = per.setdefault(p.id, {"product_id": p.id, "sku": p.sku, "name": p.name, "quantity": 0.0, "revenue": 0.0, "cost": 0.0})
            cost = ln.cost_price if ln.cost_price is not None else (p.avg_cost or p.cost_price or p.unit_cost)
            row["quantity"] += ln.quantity
            row["revenue"] += ln.quantity * (ln.unit_price or 0)
            row["cost"] += ln.quantity * cost
    rows = []
    for r in per.values():
        margin = r["revenue"] - r["cost"]
        rows.append({**r, "revenue": round(r["revenue"], 2), "cost": round(r["cost"], 2), "margin": round(margin, 2),
                     "margin_pct": round(margin / r["revenue"] * 100, 1) if r["revenue"] else 0})
    rows.sort(key=lambda r: r["margin"], reverse=True)
    revenue, cost = sum(r["revenue"] for r in rows), sum(r["cost"] for r in rows)
    return {
        "days": days,
        "rows": rows,
        "totals": {"revenue": round(revenue, 2), "cost": round(cost, 2), "margin": round(revenue - cost, 2),
                   "margin_pct": round((revenue - cost) / revenue * 100, 1) if revenue else 0},
    }


@router.get("/reports/margin")
def margin(
    days: int = 30,
    warehouse_id: int | None = None,
    category_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    """Revenue (before tax) against average cost for deliveries validated in the last `days` days."""
    return margin_rows(db, max(1, min(days, 3650)), warehouse_id, category_id)
