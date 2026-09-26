"""Stock engine: quantities, reservations, references, costing and the operation workflow."""
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import lots
from .models import Location, Operation, OperationLine, Product, Sequence, StockQuant, Warehouse

EPS = 1e-9


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


def total_on_hand(db: Session, product_id: int) -> float:
    """Units of a product across every stock (internal) location."""
    return float(
        db.scalar(
            select(func.coalesce(func.sum(StockQuant.quantity), 0))
            .join(Location, Location.id == StockQuant.location_id)
            .where(StockQuant.product_id == product_id, Location.type == "internal")
        )
        or 0
    )


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


def touch(obj) -> None:
    """Bump the optimistic-locking version: anyone still holding the old version will be told it changed."""
    obj.version = (obj.version or 1) + 1


def lock_source_stock(db: Session, op: Operation) -> None:
    """Serialise anyone who is about to use the same stock. Rows are locked in id order (no deadlocks); once we hold the
    lock every later query sees the other transaction's committed result, so the availability check that follows is
    made against the truth. Without this, two people validating at the same instant could both pass the check."""
    if op.type not in ("OUT", "INT") or op.source_location.type != "internal":
        return
    ids = {ln.product_id for ln in op.lines}
    if ids:
        db.execute(
            select(StockQuant.id)
            .where(StockQuant.location_id == op.source_location_id, StockQuant.product_id.in_(ids))
            .order_by(StockQuant.id)
            .with_for_update()
        )


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


def line_shortages(db: Session, op: Operation, qty: dict[int, float] | None = None) -> dict[int, float]:
    """line id -> missing quantity, for outbound moves from a tracked location.
    `qty` lets a caller test different quantities (partial validation) without changing the lines."""
    if op.status in ("done", "cancelled") or op.type not in ("OUT", "INT"):
        return {}
    if op.source_location.type != "internal":
        return {}
    want = {ln.id: (qty[ln.id] if qty and ln.id in qty else ln.quantity) for ln in op.lines}
    need: dict[int, float] = {}
    for ln in op.lines:
        need[ln.product_id] = need.get(ln.product_id, 0) + want[ln.id]
    out = {}
    for ln in op.lines:
        free = free_to_use(db, ln.product_id, op.source_location_id, exclude_op=op.id)
        if need[ln.product_id] > free + EPS:
            out[ln.id] = max(need[ln.product_id] - free, 0)
    return out


# ------------------------------------------------------------------ costing
def apply_costing(db: Session, pairs: list[tuple[Product, OperationLine]], src: Location, dst: Location) -> None:
    """Weighted-average cost. Call BEFORE the quantities move.
    - stock coming in (receipt, positive adjustment) blends its price into the product's average cost;
    - stock going out records the current average on the line so margin can be computed later;
    - transfers change nothing."""
    coming_in = dst.type == "internal" and src.type != "internal"
    for product, ln in pairs:
        if coming_in:
            db.execute(select(Product.id).where(Product.id == product.id).with_for_update())
            db.refresh(product)
            incoming = ln.unit_price if ln.unit_price is not None else (product.cost_price or product.unit_cost)
            before = max(total_on_hand(db, product.id), 0.0)
            total = before + ln.quantity
            product.avg_cost = round((before * (product.avg_cost or 0) + ln.quantity * incoming) / total, 4) if total > 0 else incoming
            ln.cost_price = incoming
        else:
            ln.cost_price = product.avg_cost or product.cost_price or product.unit_cost


# ------------------------------------------------------------------ workflow
class WorkflowError(Exception):
    pass


def action_todo(db: Session, op: Operation) -> str | None:
    """Draft -> Ready (or Waiting if stock is short). Returns a notification message."""
    if op.status != "draft":
        raise WorkflowError("Only draft records can be marked To Do")
    if not op.lines:
        raise WorkflowError("Add at least one product first")
    op.picked_at = op.packed_at = None
    lock_source_stock(db, op)
    touch(op)
    if line_shortages(db, op):
        op.status = "waiting"
        return "Some products are not in stock - moved to Waiting"
    op.status = "ready"
    return None


def action_check(db: Session, op: Operation) -> str | None:
    """Waiting -> Ready once stock is available."""
    if op.status != "waiting":
        raise WorkflowError("Only waiting records can be re-checked")
    lock_source_stock(db, op)
    if line_shortages(db, op):
        return "Still waiting for stock"
    op.status = "ready"
    touch(op)
    return None


def action_validate(
    db: Session, op: Operation, done: dict[int, float] | None = None, backorder: bool = True
) -> str | None:
    """Ready -> Done. `done` maps line id -> quantity actually received/shipped (default: everything).
    A shortfall either creates a backorder for the rest (default) or cancels the remainder."""
    if op.status != "ready":
        raise WorkflowError("Only ready records can be validated")

    qty = {ln.id: ln.quantity for ln in op.lines}
    for lid, q in (done or {}).items():
        if lid not in qty:
            raise WorkflowError("That line does not belong to this record")
        if q < 0:
            raise WorkflowError("Quantities can't be negative")
        if q > qty[lid] + EPS:
            raise WorkflowError("You can't process more than was ordered")
        qty[lid] = q
    if not any(q > EPS for q in qty.values()):
        raise WorkflowError("Enter a quantity for at least one product")

    lock_source_stock(db, op)
    if line_shortages(db, op, qty):
        op.status = "waiting"
        op.picked_at = op.packed_at = None
        touch(op)
        return "Not enough stock - moved back to Waiting"
    if op.type == "OUT" and not op.packed_at:
        raise WorkflowError("Pick and pack the items before validating the delivery")

    partial = any(qty[ln.id] < ln.quantity - EPS for ln in op.lines)
    remainder = []
    if partial:
        for ln in list(op.lines):
            short = ln.quantity - qty[ln.id]
            if short > EPS:
                remainder.append((ln.product_id, short, ln.unit_price, ln.tax_rate, ln.tax_name, ln.lot_no, ln.expiry_date))
                ln.ordered_qty = ln.quantity
                if qty[ln.id] <= EPS:
                    op.lines.remove(ln)  # nothing moved for this line, it lives on in the backorder
                else:
                    ln.quantity = qty[ln.id]
        db.flush()

    apply_costing(db, [(ln.product, ln) for ln in op.lines], op.source_location, op.dest_location)
    for ln in op.lines:
        add_qty(db, ln.product_id, op.source_location, -ln.quantity)
        add_qty(db, ln.product_id, op.dest_location, ln.quantity)
        if op.type == "OUT":
            lots.consume(db, ln.product_id, ln.quantity)
    if op.type == "IN":
        lots.receive(db, op)
    op.status = "done"
    op.done_at = utcnow()
    touch(op)

    message = None
    if partial and backorder:
        bo = Operation(
            reference=next_reference(db, op.warehouse, op.type), type=op.type, status="draft", contact=op.contact,
            party_id=op.party_id, schedule_date=op.schedule_date, responsible_id=op.responsible_id,
            warehouse_id=op.warehouse_id, source_location_id=op.source_location_id, dest_location_id=op.dest_location_id,
            backorder_of_id=op.id,
        )
        for pid, q, price, rate, name, lot_no, expiry in remainder:
            bo.lines.append(OperationLine(product_id=pid, quantity=q, unit_price=price, tax_rate=rate, tax_name=name, lot_no=lot_no, expiry_date=expiry))
        db.add(bo)
        db.flush()
        action_todo(db, bo)
        message = f"Validated part of the order. Backorder {bo.reference} created for the rest."
    elif partial:
        message = "Validated part of the order. The remainder was cancelled."
    promote_waiting(db)
    return message


def action_pick(db: Session, op: Operation) -> None:
    if op.type != "OUT":
        raise WorkflowError("Only deliveries are picked and packed")
    if op.status != "ready":
        raise WorkflowError("A delivery can be picked once it is Ready")
    if op.picked_at:
        raise WorkflowError("Items are already picked")
    op.picked_at = utcnow()
    touch(op)


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
    touch(op)


def action_cancel(db: Session, op: Operation) -> None:
    if op.status in ("done", "cancelled"):
        raise WorkflowError("This record can no longer be cancelled")
    op.status = "cancelled"
    touch(op)


def promote_waiting(db: Session) -> None:
    """After stock arrives, waiting orders that can now be served become Ready."""
    db.flush()
    for op in db.scalars(select(Operation).where(Operation.status == "waiting").order_by(Operation.id)):
        if not line_shortages(db, op):
            op.status = "ready"
            op.picked_at = op.packed_at = None
            touch(op)
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
    line = OperationLine(product_id=product.id, quantity=abs(delta), unit_price=product.cost_price or product.unit_cost)
    op.lines.append(line)
    db.add(op)
    apply_costing(db, [(product, line)], src, dst)
    add_qty(db, product.id, location, delta)
    if delta < 0:
        lots.consume(db, product.id, -delta)
    promote_waiting(db)
    return op
