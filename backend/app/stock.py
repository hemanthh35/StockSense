"""Stock engine: quantities, reservations, references and the operation workflow."""
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Location, Operation, OperationLine, Product, Sequence, StockQuant, Warehouse


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def next_reference(db: Session, wh: Warehouse, op_type: str) -> str:
    key = f"{wh.id}/{op_type}"
    seq = db.execute(select(Sequence).where(Sequence.key == key).with_for_update()).scalar_one_or_none()
    if seq is None:
        seq = Sequence(key=key, value=0)
        db.add(seq)
    seq.value += 1
    db.flush()
    return f"{wh.short_code}/{op_type}/{seq.value:04d}"


def on_hand(db: Session, product_id: int, location_id: int) -> float:
    return db.scalar(
        select(StockQuant.quantity).where(
            StockQuant.product_id == product_id, StockQuant.location_id == location_id
        )
    ) or 0.0


def reserved(db: Session, product_id: int, location_id: int, exclude_op: int | None = None) -> float:
    stmt = (
        select(func.coalesce(func.sum(OperationLine.quantity), 0))
        .join(Operation, Operation.id == OperationLine.operation_id)
        .where(
            Operation.status == "ready",
            Operation.type.in_(["OUT", "INT"]),
            Operation.source_location_id == location_id,
            OperationLine.product_id == product_id,
        )
    )
    if exclude_op:
        stmt = stmt.where(Operation.id != exclude_op)
    return float(db.scalar(stmt) or 0)


def free_to_use(db: Session, product_id: int, location_id: int, exclude_op: int | None = None) -> float:
    return on_hand(db, product_id, location_id) - reserved(db, product_id, location_id, exclude_op)


def add_qty(db: Session, product_id: int, location: Location, delta: float) -> None:
    if location.type != "internal":
        return
    q = db.execute(
        select(StockQuant)
        .where(StockQuant.product_id == product_id, StockQuant.location_id == location.id)
        .with_for_update()
    ).scalar_one_or_none()
    if q is None:
        q = StockQuant(product_id=product_id, location_id=location.id, quantity=0)
        db.add(q)
    q.quantity = (q.quantity or 0) + delta
    db.flush()


def line_shortages(db: Session, op: Operation) -> dict[int, float]:
    """line id -> missing quantity, for outbound moves from a tracked location."""
    if op.status in ("done", "cancelled") or op.type not in ("OUT", "INT"):
        return {}
    if op.source_location.type != "internal":
        return {}
    need: dict[int, float] = {}
    for ln in op.lines:
        need[ln.product_id] = need.get(ln.product_id, 0) + ln.quantity
    out = {}
    for ln in op.lines:
        free = free_to_use(db, ln.product_id, op.source_location_id, exclude_op=op.id)
        if need[ln.product_id] > free + 1e-9:
            out[ln.id] = max(need[ln.product_id] - free, 0)
    return out


class WorkflowError(Exception):
    pass


def action_todo(db: Session, op: Operation) -> str | None:
    """Draft -> Ready (or Waiting if stock is short). Returns a notification message."""
    if op.status != "draft":
        raise WorkflowError("Only draft records can be marked To Do")
    if not op.lines:
        raise WorkflowError("Add at least one product first")
    op.picked_at = op.packed_at = None
    if line_shortages(db, op):
        op.status = "waiting"
        return "Some products are not in stock - moved to Waiting"
    op.status = "ready"
    return None


def action_check(db: Session, op: Operation) -> str | None:
    """Waiting -> Ready once stock is available."""
    if op.status != "waiting":
        raise WorkflowError("Only waiting records can be re-checked")
    if line_shortages(db, op):
        return "Still waiting for stock"
    op.status = "ready"
    return None


def action_validate(db: Session, op: Operation) -> str | None:
    if op.status != "ready":
        raise WorkflowError("Only ready records can be validated")
    if line_shortages(db, op):
        op.status = "waiting"
        op.picked_at = op.packed_at = None
        return "Not enough stock - moved back to Waiting"
    if op.type == "OUT" and not op.packed_at:
        raise WorkflowError("Pick and pack the items before validating the delivery")
    for ln in op.lines:
        add_qty(db, ln.product_id, op.source_location, -ln.quantity)
        add_qty(db, ln.product_id, op.dest_location, ln.quantity)
    op.status = "done"
    op.done_at = utcnow()
    promote_waiting(db)
    return None


def action_pick(db: Session, op: Operation) -> None:
    if op.type != "OUT":
        raise WorkflowError("Only deliveries are picked and packed")
    if op.status != "ready":
        raise WorkflowError("A delivery can be picked once it is Ready")
    if op.picked_at:
        raise WorkflowError("Items are already picked")
    op.picked_at = utcnow()


def action_pack(db: Session, op: Operation) -> None:
    if op.type != "OUT":
        raise WorkflowError("Only deliveries are picked and packed")
    if op.status != "ready":
        raise WorkflowError("A delivery can be packed once it is Ready")
    if not op.picked_at:
        raise WorkflowError("Pick the items before packing them")
    if op.packed_at:
        raise WorkflowError("Items are already packed")
    op.packed_at = utcnow()


def action_cancel(db: Session, op: Operation) -> None:
    if op.status in ("done", "cancelled"):
        raise WorkflowError("This record can no longer be cancelled")
    op.status = "cancelled"


def promote_waiting(db: Session) -> None:
    """After stock arrives, waiting orders that can now be served become Ready."""
    db.flush()
    for op in db.scalars(select(Operation).where(Operation.status == "waiting").order_by(Operation.id)):
        if not line_shortages(db, op):
            op.status = "ready"
            op.picked_at = op.packed_at = None
            db.flush()


def adjust(db: Session, product: Product, location: Location, counted: float, user_id: int | None) -> Operation:
    """Set on-hand to the counted quantity and log the difference as a done ADJ operation."""
    current = on_hand(db, product.id, location.id)
    delta = counted - current
    adj_loc = db.scalar(select(Location).where(Location.type == "adjustment"))
    wh = location.warehouse
    if delta >= 0:
        src, dst = adj_loc, location
    else:
        src, dst = location, adj_loc
    op = Operation(
        reference=next_reference(db, wh, "ADJ"),
        type="ADJ",
        status="done",
        contact="Inventory Adjustment",
        schedule_date=date.today(),
        responsible_id=user_id,
        warehouse_id=wh.id,
        source_location_id=src.id,
        dest_location_id=dst.id,
        done_at=utcnow(),
    )
    op.lines.append(OperationLine(product_id=product.id, quantity=abs(delta), unit_price=product.unit_cost))
    db.add(op)
    add_qty(db, product.id, location, delta)
    promote_waiting(db)
    return op
