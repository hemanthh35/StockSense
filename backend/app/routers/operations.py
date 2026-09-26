from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import pricing, stock
from ..db import get_db
from ..deps import current_user
from ..models import Location, Operation, OperationLine, Product, User, Warehouse

router = APIRouter(tags=["operations"])

TYPES = {"IN": "Receipt", "OUT": "Delivery", "INT": "Internal Transfer", "ADJ": "Adjustment"}


class LineIn(BaseModel):
    product_id: int
    quantity: float
    unit_price: float | None = None  # blank = product's unit cost


class OperationIn(BaseModel):
    type: str
    contact: str | None = None
    schedule_date: date | None = None
    warehouse_id: int | None = None
    source_location_id: int | None = None
    dest_location_id: int | None = None
    lines: list[LineIn] = []


def loc_brief(l: Location) -> dict:
    return {"id": l.id, "name": l.full_name, "type": l.type}


def direction_of(op: Operation) -> str:
    """in = green, out = red, transfer = neutral (based on tracked locations)."""
    s, d = op.source_location.type == "internal", op.dest_location.type == "internal"
    if d and not s:
        return "in"
    if s and not d:
        return "out"
    return "transfer"


def op_out(db: Session, op: Operation, with_lines: bool = True) -> dict:
    short = stock.line_shortages(db, op) if with_lines else {}
    data = {
        "id": op.id,
        "reference": op.reference,
        "type": op.type,
        "type_label": TYPES[op.type],
        "status": op.status,
        "contact": op.contact,
        "schedule_date": op.schedule_date.isoformat() if op.schedule_date else None,
        "late": bool(
            op.schedule_date and op.schedule_date < date.today() and op.status not in ("done", "cancelled")
        ),
        "responsible": op.responsible.login_id if op.responsible else None,
        "warehouse": {"id": op.warehouse.id, "name": op.warehouse.name, "short_code": op.warehouse.short_code},
        "source_location": loc_brief(op.source_location),
        "dest_location": loc_brief(op.dest_location),
        "direction": direction_of(op),
    }
    data.update(pricing.op_totals(op))
    if with_lines:
        data["lines"] = [
            {
                "id": ln.id,
                "product_id": ln.product_id,
                "product": f"[{ln.product.sku}] {ln.product.name}",
                "quantity": ln.quantity,
                "unit_price": ln.unit_price or 0,
                "tax_rate": ln.tax_rate or 0,
                "tax_name": ln.tax_name,
                "subtotal": pricing.line_amounts(ln)[0],
                "tax_amount": pricing.line_amounts(ln)[1],
                "short": ln.id in short,
                "missing": short.get(ln.id, 0),
            }
            for ln in op.lines
        ]
    return data


def _load(db: Session, op_id: int) -> Operation:
    op = db.scalar(
        select(Operation)
        .options(joinedload(Operation.lines).joinedload(OperationLine.product))
        .where(Operation.id == op_id)
    )
    if not op:
        raise HTTPException(404, "Record not found")
    return op


def _default_locations(db: Session, body: OperationIn, wh: Warehouse) -> tuple[int, int]:
    internal = db.scalar(
        select(Location).where(Location.warehouse_id == wh.id, Location.type == "internal").order_by(Location.id)
    )
    vendor = db.scalar(select(Location).where(Location.type == "vendor"))
    customer = db.scalar(select(Location).where(Location.type == "customer"))
    if not internal:
        raise HTTPException(422, "This warehouse has no stock location yet")
    src, dst = body.source_location_id, body.dest_location_id
    if body.type == "IN":
        src, dst = src or vendor.id, dst or internal.id
    elif body.type == "OUT":
        src, dst = src or internal.id, dst or customer.id
    elif not src or not dst:
        raise HTTPException(422, "Internal transfers need a From and To location")
    return src, dst


def _validate_lines(db: Session, lines: list[LineIn]) -> None:
    for ln in lines:
        if ln.quantity <= 0:
            raise HTTPException(422, "Quantity must be greater than zero")
        if not db.get(Product, ln.product_id):
            raise HTTPException(422, "Unknown product")


def _make_lines(db: Session, lines: list[LineIn]) -> list[OperationLine]:
    out = []
    for l in lines:
        product = db.get(Product, l.product_id)
        ln = OperationLine(product_id=product.id, quantity=l.quantity)
        pricing.fill_line(ln, product, l.unit_price)
        out.append(ln)
    return out


@router.get("/contacts")
def contacts(type: str | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Previously used contacts, so they can be picked instead of retyped."""
    stmt = select(Operation.contact).where(Operation.contact.isnot(None), Operation.contact != "Inventory Adjustment").distinct()
    if type:
        stmt = stmt.where(Operation.type == type)
    return sorted(c for c in db.scalars(stmt) if c.strip())


@router.get("/operations")
def list_operations(
    type: str | None = None,
    status: str | None = None,
    q: str | None = None,
    warehouse_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    stmt = select(Operation).options(selectinload(Operation.lines)).order_by(Operation.id.desc())
    if type:
        stmt = stmt.where(Operation.type == type)
    if status:
        stmt = stmt.where(Operation.status == status)
    if warehouse_id:
        stmt = stmt.where(Operation.warehouse_id == warehouse_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Operation.reference.ilike(like), Operation.contact.ilike(like)))
    return [op_out(db, o, with_lines=False) for o in db.scalars(stmt)]


@router.post("/operations", status_code=201)
def create_operation(body: OperationIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.type not in ("IN", "OUT", "INT"):
        raise HTTPException(422, "Type must be IN, OUT or INT (use Stock > Update for adjustments)")
    wh = db.get(Warehouse, body.warehouse_id) if body.warehouse_id else db.scalar(select(Warehouse).order_by(Warehouse.id))
    if not wh:
        raise HTTPException(422, "Create a warehouse first")
    _validate_lines(db, body.lines)
    src, dst = _default_locations(db, body, wh)
    op = Operation(
        reference=stock.next_reference(db, wh, body.type),
        type=body.type,
        status="draft",
        contact=body.contact,
        schedule_date=body.schedule_date or date.today(),
        responsible_id=user.id,
        warehouse_id=wh.id,
        source_location_id=src,
        dest_location_id=dst,
    )
    op.lines = _make_lines(db, body.lines)
    db.add(op)
    db.commit()
    return op_out(db, _load(db, op.id))


@router.get("/operations/{op_id}")
def get_operation(op_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return op_out(db, _load(db, op_id))


@router.put("/operations/{op_id}")
def update_operation(op_id: int, body: OperationIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    op = _load(db, op_id)
    if op.status not in ("draft", "waiting", "ready"):
        raise HTTPException(409, "Finished records cannot be edited")
    _validate_lines(db, body.lines)
    op.contact = body.contact
    if body.schedule_date:
        op.schedule_date = body.schedule_date
    if body.source_location_id:
        op.source_location_id = body.source_location_id
    if body.dest_location_id:
        op.dest_location_id = body.dest_location_id
    op.lines = _make_lines(db, body.lines)
    if op.status != "draft":  # edits invalidate the earlier availability check
        op.status = "draft"
    db.commit()
    return op_out(db, _load(db, op_id))


@router.post("/operations/{op_id}/{action}")
def operation_action(op_id: int, action: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    op = _load(db, op_id)
    message = None
    if action == "duplicate":
        if op.type == "ADJ":
            raise HTTPException(409, "Adjustments cannot be duplicated")
        copy = Operation(
            reference=stock.next_reference(db, op.warehouse, op.type), type=op.type, status="draft", contact=op.contact,
            schedule_date=date.today(), responsible_id=user.id, warehouse_id=op.warehouse_id,
            source_location_id=op.source_location_id, dest_location_id=op.dest_location_id,
        )
        copy.lines = _make_lines(db, [LineIn(product_id=l.product_id, quantity=l.quantity) for l in op.lines])
        db.add(copy)
        db.commit()
        return op_out(db, _load(db, copy.id))
    try:
        if action == "todo":
            message = stock.action_todo(db, op)
        elif action == "check":
            message = stock.action_check(db, op)
        elif action == "validate":
            message = stock.action_validate(db, op)
        elif action == "cancel":
            stock.action_cancel(db, op)
        else:
            raise HTTPException(404, "Unknown action")
    except stock.WorkflowError as e:
        raise HTTPException(409, str(e))
    db.commit()
    out = op_out(db, _load(db, op_id))
    out["message"] = message
    return out


@router.get("/moves")
def move_history(
    q: str | None = None,
    status: str | None = None,
    direction: str | None = None,
    warehouse_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    """One row per product line; drafts and cancelled records are not moves yet."""
    stmt = (
        select(Operation)
        .options(joinedload(Operation.lines).joinedload(OperationLine.product))
        .where(Operation.status.notin_(["draft", "cancelled"]))
        .order_by(Operation.id.desc())
    )
    if status:
        stmt = stmt.where(Operation.status == status)
    if warehouse_id:
        stmt = stmt.where(Operation.warehouse_id == warehouse_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Operation.reference.ilike(like), Operation.contact.ilike(like)))
    rows = []
    for op in db.scalars(stmt).unique():
        d = direction_of(op)
        if direction and d != direction:
            continue
        when = op.done_at.date() if op.done_at else op.schedule_date
        for ln in op.lines:
            rows.append(
                {
                    "operation_id": op.id,
                    "reference": op.reference,
                    "type": op.type,
                    "contact": op.contact,
                    "status": op.status,
                    "date": when.isoformat() if when else None,
                    "from": op.source_location.full_name,
                    "to": op.dest_location.full_name,
                    "product": f"[{ln.product.sku}] {ln.product.name}",
                    "quantity": ln.quantity,
                    "direction": d,
                }
            )
    return rows
