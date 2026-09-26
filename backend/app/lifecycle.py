"""Can a product / location / warehouse be archived or deleted? Answers come from real usage:
stock still on hand, open (unfinished) documents, or any document history at all."""
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import Session

from .models import Location, Operation, OperationLine, StockQuant

OPEN = ("draft", "waiting", "ready")


def _on_hand(db: Session, *conds) -> float:
    return float(db.scalar(select(func.coalesce(func.sum(StockQuant.quantity), 0)).where(*conds)) or 0)


def product_usage(db: Session, pid: int) -> dict:
    open_ops = db.scalar(
        select(func.count(distinct(Operation.id)))
        .join(OperationLine, OperationLine.operation_id == Operation.id)
        .where(OperationLine.product_id == pid, Operation.status.in_(OPEN))
    ) or 0
    history = db.scalar(select(func.count()).select_from(OperationLine).where(OperationLine.product_id == pid)) or 0
    return {"on_hand": _on_hand(db, StockQuant.product_id == pid), "open_ops": open_ops, "history": history}


def party_usage(db: Session, pid: int) -> dict:
    return {
        "on_hand": 0.0,
        "open_ops": db.scalar(select(func.count()).select_from(Operation).where(Operation.party_id == pid, Operation.status.in_(OPEN))) or 0,
        "history": db.scalar(select(func.count()).select_from(Operation).where(Operation.party_id == pid)) or 0,
    }


def location_usage(db: Session, lid: int) -> dict:
    touches = or_(Operation.source_location_id == lid, Operation.dest_location_id == lid)
    return {
        "on_hand": _on_hand(db, StockQuant.location_id == lid),
        "open_ops": db.scalar(select(func.count()).select_from(Operation).where(touches, Operation.status.in_(OPEN))) or 0,
        "history": db.scalar(select(func.count()).select_from(Operation).where(touches)) or 0,
    }


def warehouse_usage(db: Session, wid: int) -> dict:
    loc_ids = select(Location.id).where(Location.warehouse_id == wid)
    touches = or_(
        Operation.warehouse_id == wid, Operation.source_location_id.in_(loc_ids), Operation.dest_location_id.in_(loc_ids)
    )
    return {
        "on_hand": _on_hand(db, StockQuant.location_id.in_(loc_ids)),
        "open_ops": db.scalar(select(func.count()).select_from(Operation).where(touches, Operation.status.in_(OPEN))) or 0,
        "history": db.scalar(select(func.count()).select_from(Operation).where(touches)) or 0,
    }


def archive_blocker(usage: dict, what: str) -> str | None:
    """Reason this thing can't be archived yet, or None."""
    if usage["on_hand"] > 0:
        return f"{what} still holds {usage['on_hand']:g} units of stock - move it out or adjust it to zero first"
    if usage["open_ops"]:
        n = usage["open_ops"]
        return f"{what} is used by {n} open document{'s' if n > 1 else ''} - finish or cancel {'them' if n > 1 else 'it'} first"
    return None


def delete_blocker(usage: dict, what: str) -> str | None:
    """Only things that were never used can be deleted; everything else is archived to keep history intact."""
    if usage["history"] or usage["on_hand"] > 0:
        return f"{what} has history and can't be deleted - archive it instead"
    return None
