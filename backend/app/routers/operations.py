from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import pricing, stock
from ..filters import op_filters
from ..db import get_db
from ..deps import current_user
from ..models import Location, Operation, OperationLine, Party, Product, User, Warehouse
from .parties import brief as party_brief

router = APIRouter(tags=["operations"])

TYPES = {"IN": "Receipt", "OUT": "Delivery", "INT": "Internal Transfer", "ADJ": "Adjustment"}


class LineIn(BaseModel):
    product_id: int
    quantity: float
    unit_price: float | None = None  # blank = product's unit cost


class ValidateLine(BaseModel):
    line_id: int
    done_qty: float


class ValidateIn(BaseModel):
    """Optional body for /validate: quantities actually processed, and what to do with the rest."""

    lines: list[ValidateLine] | None = None
    backorder: bool = True


class OperationIn(BaseModel):
    type: str
    contact: str | None = None
    party_id: int | None = None  # a saved supplier/customer; its name becomes the contact
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
        "party": party_brief(op.party) if op.party else None,
        "schedule_date": op.schedule_date.isoformat() if op.schedule_date else None,
        "late": bool(
            op.schedule_date and op.schedule_date < date.today() and op.status not in ("done", "cancelled")
        ),
        "responsible": op.responsible.login_id if op.responsible else None,
        "warehouse": {"id": op.warehouse.id, "name": op.warehouse.name, "short_code": op.warehouse.short_code},
        "source_location": loc_brief(op.source_location),
        "dest_location": loc_brief(op.dest_location),
        "direction": direction_of(op),
        "picked": op.picked_at is not None,
        "packed": op.packed_at is not None,
    }
    data.update(pricing.op_totals(op))
    if with_lines:
        data["lines"] = [
            {
                "id": ln.id,
                "product_id": ln.product_id,
                "product": f"[{ln.product.sku}] {ln.product.name}",
                "quantity": ln.quantity,
                "ordered_qty": ln.ordered_qty,
                "cost_price": ln.cost_price,
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
        data["backorder_of"] = None
        if op.backorder_of_id:
            src = db.get(Operation, op.backorder_of_id)
            data["backorder_of"] = {"id": src.id, "reference": src.reference, "type": src.type} if src else None
        data["backorders"] = [
            {"id": b.id, "reference": b.reference, "status": b.status, "type": b.type}
            for b in db.scalars(select(Operation).where(Operation.backorder_of_id == op.id).order_by(Operation.id))
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


def _resolve_locations(db: Session, op_type: str, warehouse_id: int | None, src_id: int | None, dst_id: int | None):
    """Work out (warehouse, source, dest). Receipts/deliveries live in one warehouse;
    internal transfers may cross warehouses and take their warehouse from the From location."""

    def get(i):
        loc = db.get(Location, i) if i else None
        if i and not loc:
            raise HTTPException(422, "Unknown location")
        return loc

    src, dst = get(src_id), get(dst_id)
    wh = None
    if warehouse_id:
        wh = db.get(Warehouse, warehouse_id)
        if not wh:
            raise HTTPException(422, "Unknown warehouse")

    if op_type == "INT":
        if not src or not dst:
            raise HTTPException(422, "Internal transfers need a From and To location")
        if src.type != "internal" or dst.type != "internal":
            raise HTTPException(422, "Transfers can only move stock between stock locations")
        if not src.active or not dst.active:
            raise HTTPException(422, "That location is archived")
        if src.id == dst.id:
            raise HTTPException(422, "From and To must be different locations")
        return src.warehouse, src, dst

    tracked = dst if op_type == "IN" else src
    if tracked is None:
        wh = wh or db.scalar(select(Warehouse).where(Warehouse.active.is_(True)).order_by(Warehouse.id))
        if not wh:
            raise HTTPException(422, "Create a warehouse first")
        tracked = db.scalar(
            select(Location)
            .where(Location.warehouse_id == wh.id, Location.type == "internal", Location.active.is_(True))
            .order_by(Location.id)
        )
        if not tracked:
            raise HTTPException(422, "This warehouse has no stock location yet")
    if tracked.type != "internal":
        raise HTTPException(422, "Choose a stock location")
    if not tracked.active:
        raise HTTPException(422, "That location is archived")
    if wh and tracked.warehouse_id != wh.id:
        raise HTTPException(422, "That location belongs to a different warehouse")
    wh = wh or tracked.warehouse
    vendor = db.scalar(select(Location).where(Location.type == "vendor"))
    customer = db.scalar(select(Location).where(Location.type == "customer"))
    return (wh, vendor, tracked) if op_type == "IN" else (wh, tracked, customer)


def _party_for(db: Session, op_type: str, party_id: int | None) -> Party | None:
    """Look up the chosen contact and make sure it suits the document (suppliers for receipts, customers for deliveries)."""
    if not party_id or op_type in ("INT", "ADJ"):
        return None
    p = db.get(Party, party_id)
    if not p:
        raise HTTPException(422, "Unknown contact")
    if not p.active:
        raise HTTPException(422, f"{p.name} is archived")
    if op_type == "IN" and p.kind == "customer":
        raise HTTPException(422, f"{p.name} is a customer, not a supplier")
    if op_type == "OUT" and p.kind == "vendor":
        raise HTTPException(422, f"{p.name} is a supplier, not a customer")
    return p


def _validate_lines(db: Session, lines: list[LineIn]) -> None:
    for ln in lines:
        if ln.quantity <= 0:
            raise HTTPException(422, "Quantity must be greater than zero")
        product = db.get(Product, ln.product_id)
        if not product:
            raise HTTPException(422, "Unknown product")
        if not product.active:
            raise HTTPException(422, f"{product.sku} is archived and can't be used on new documents")


def _make_lines(db: Session, lines: list[LineIn], op_type: str | None = None) -> list[OperationLine]:
    out = []
    for l in lines:
        product = db.get(Product, l.product_id)
        ln = OperationLine(product_id=product.id, quantity=l.quantity)
        pricing.fill_line(ln, product, l.unit_price, op_type)
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
    location_id: int | None = None,
    category_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    stmt = op_filters(
        select(Operation).options(selectinload(Operation.lines)).order_by(Operation.id.desc()),
        type=type, status=status, warehouse_id=warehouse_id, location_id=location_id, category_id=category_id, q=q,
    )
    return [op_out(db, o, with_lines=False) for o in db.scalars(stmt)]


@router.post("/operations", status_code=201)
def create_operation(body: OperationIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.type not in ("IN", "OUT", "INT"):
        raise HTTPException(422, "Type must be IN, OUT or INT (use Stock > Update for adjustments)")
    _validate_lines(db, body.lines)
    wh, src, dst = _resolve_locations(db, body.type, body.warehouse_id, body.source_location_id, body.dest_location_id)
    party = _party_for(db, body.type, body.party_id)
    op = Operation(
        reference=stock.next_reference(db, wh, body.type),
        type=body.type,
        status="draft",
        contact=party.name if party else body.contact,
        party_id=party.id if party else None,
        schedule_date=body.schedule_date or date.today(),
        responsible_id=user.id,
        warehouse_id=wh.id,
        source_location_id=src.id,
        dest_location_id=dst.id,
    )
    op.lines = _make_lines(db, body.lines, body.type)
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
    party = _party_for(db, op.type, body.party_id)
    op.party_id = party.id if party else None
    op.contact = party.name if party else body.contact
    if body.schedule_date:
        op.schedule_date = body.schedule_date
    # the warehouse (and so the reference prefix) is fixed once the document exists
    _, src, dst = _resolve_locations(
        db, op.type, op.warehouse_id if op.type != "INT" else None, body.source_location_id, body.dest_location_id
    )
    op.source_location_id, op.dest_location_id = src.id, dst.id
    op.lines = _make_lines(db, body.lines, op.type)
    if op.status != "draft":  # edits invalidate the earlier availability check
        op.status = "draft"
    op.picked_at = op.packed_at = None
    db.commit()
    return op_out(db, _load(db, op_id))


@router.post("/operations/{op_id}/{action}")
def operation_action(
    op_id: int, action: str, body: ValidateIn | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)
):
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
        copy.lines = _make_lines(db, [LineIn(product_id=l.product_id, quantity=l.quantity) for l in op.lines], op.type)
        db.add(copy)
        db.commit()
        return op_out(db, _load(db, copy.id))
    try:
        if action == "todo":
            message = stock.action_todo(db, op)
        elif action == "check":
            message = stock.action_check(db, op)
        elif action == "pick":
            stock.action_pick(db, op)
        elif action == "pack":
            stock.action_pack(db, op)
        elif action == "validate":
            done = {l.line_id: l.done_qty for l in body.lines} if body and body.lines else None
            message = stock.action_validate(db, op, done, body.backorder if body else True)
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
    type: str | None = None,
    warehouse_id: int | None = None,
    location_id: int | None = None,
    category_id: int | None = None,
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
    stmt = op_filters(
        stmt, type=type, status=status, warehouse_id=warehouse_id, location_id=location_id, category_id=category_id, q=q
    )
    rows = []
    for op in db.scalars(stmt).unique():
        d = direction_of(op)
        if direction and d != direction:
            continue
        when = op.done_at.date() if op.done_at else op.schedule_date
        needle = (q or "").lower()
        op_match = not needle or needle in op.reference.lower() or needle in (op.contact or "").lower()
        for ln in op.lines:
            label = f"[{ln.product.sku}] {ln.product.name}"
            if not op_match and needle not in label.lower():
                continue  # searching a product: hide the other products on the same document
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
