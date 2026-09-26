"""Batches and expiry. A receipt line may carry a lot number and an expiry date; validating the receipt records the lot.
Deliveries (and negative stock counts) use up the lots that expire first (FEFO). Lots are tracked per product, not per
location: they answer "what is about to expire?" without changing how quantities are stored."""
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Operation, OperationLine, StockLot
from .queries import cost_expr

EPS = 1e-9


def receive(db: Session, op: Operation) -> None:
    """Record the lots of a validated receipt. A line with an expiry but no lot number gets the receipt reference as its lot."""
    for ln in op.lines:
        if not (ln.lot_no or ln.expiry_date) or ln.quantity <= EPS:
            continue
        lot_no = (ln.lot_no or op.reference)[:40]
        lot = db.scalar(select(StockLot).where(StockLot.product_id == ln.product_id, StockLot.lot_no == lot_no).with_for_update())
        if lot is None:
            db.add(StockLot(product_id=ln.product_id, lot_no=lot_no, expiry_date=ln.expiry_date, received_qty=ln.quantity,
                            remaining_qty=ln.quantity, received_on=date.today(), source_ref=op.reference))
        else:
            lot.received_qty = float(lot.received_qty) + ln.quantity
            lot.remaining_qty = float(lot.remaining_qty) + ln.quantity
            lot.expiry_date = ln.expiry_date or lot.expiry_date
    db.flush()


def consume(db: Session, product_id: int, qty: float) -> None:
    """Use up `qty` units from the lots that expire first. Units that were never in a tracked lot are simply not counted."""
    if qty <= EPS:
        return
    lots = db.scalars(
        select(StockLot).where(StockLot.product_id == product_id, StockLot.remaining_qty > 0)
        .order_by(StockLot.expiry_date.asc().nulls_last(), StockLot.id).with_for_update()
    ).all()
    for lot in lots:
        take = min(float(lot.remaining_qty), qty)
        lot.remaining_qty = float(lot.remaining_qty) - take
        qty -= take
        if qty <= EPS:
            break
    db.flush()


def summary(db: Session, days: int = 30) -> dict:
    """Counts of lots still on the shelf: expired, expiring within `days`, later, or with no expiry. Plus the cost of the expired ones."""
    today, soon = date.today(), date.today() + timedelta(days=days)
    from .models import Product
    live = StockLot.remaining_qty > 0
    expired, expiring, later, none, value = db.execute(
        select(
            func.count().filter(StockLot.expiry_date < today),
            func.count().filter(StockLot.expiry_date >= today, StockLot.expiry_date <= soon),
            func.count().filter(StockLot.expiry_date > soon),
            func.count().filter(StockLot.expiry_date.is_(None)),
            func.coalesce(func.sum(StockLot.remaining_qty * cost_expr()).filter(StockLot.expiry_date < today), 0),
        ).select_from(StockLot).join(Product, Product.id == StockLot.product_id).where(live)
    ).one()
    return {"expired": expired, "expiring_soon": expiring, "later": later, "no_expiry": none, "expired_value": round(float(value), 2), "days": days}
