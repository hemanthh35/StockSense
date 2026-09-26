from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, not_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, joinedload, selectinload

from .. import audit, pricing, stock
from ..conflict import check_version
from ..db import get_db
from ..deps import current_user, ensure_can_edit_docs
from ..filters import op_filters
from ..models import Location, Operation, OperationLine, Party, Product, User, Warehouse
from ..pagination import PageParams, count_rows, envelope, slice_stmt
from .parties import brief as party_brief

router = APIRouter(tags=["operations"])

TYPES = {"IN": "Receipt", "OUT": "Delivery", "INT": "Internal Transfer", "ADJ": "Adjustment"}
BIG = 1_000_000_000
NOT_ENOUGH = "Not enough stock: someone else just used it. Please review the document and try again."


class LineIn(BaseModel):
    product_id: int
    quantity: Annotated[float, Field(le=BIG)]
    unit_price: Annotated[float, Field(ge=0, le=BIG)] | None = None  # blank = the product's default price


class ValidateLine(BaseModel):
    line_id: int
    done_qty: Annotated[float, Field(le=BIG)]


class ValidateIn(BaseModel):
    """Optional body for /validate: quantities actually processed, and what to do with the rest."""

    lines: list[ValidateLine] | None = Field(default=None, max_length=500)
    backorder: bool = True


class OperationIn(BaseModel):
    type: str = Field(max_length=3)
    contact: str | None = Field(default=None, max_length=150)
    party_id: int | None = None  # a saved supplier/customer; its name becomes the contact
    schedule_date: date | None = None
    warehouse_id: int | None = None
    source_location_id: int | None = None
    dest_location_id: int | None = None
    lines: list[LineIn] = Field(default=[], max_length=500)
    version: int | None = None  # the version the editor loaded, for optimistic locking


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
        "version": op.version,
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
    if not lines:
        return
    ids = {ln.product_id for ln in lines}
    found = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids)))}  # one query, not one per line
    for ln in lines:
        if ln.quantity <= 0:
            raise HTTPException(422, "Quantity must be greater than zero")
        product = found.get(ln.product_id)
        if not product:
            raise HTTPException(422, "Unknown product")
        if not product.active:
            raise HTTPException(422, f"{product.sku} is archived and can't be used on new documents")


def _make_lines(db: Session, lines: list[LineIn], op_type: str | None = None) -> list[OperationLine]:
    if not lines:
        return []
    ids = {l.product_id for l in lines}
    found = {p.id: p for p in db.scalars(select(Product).options(joinedload(Product.tax)).where(Product.id.in_(ids)))}
    out = []
    for l in lines:
        product = found[l.product_id]
        ln = OperationLine(product_id=product.id, quantity=l.quantity)
        pricing.fill_line(ln, product, l.unit_price, op_type)
        out.append(ln)
    return out


def _lines_summary(lines) -> str:
    n = len(lines)
    qty = sum(float(l.quantity) for l in lines)
    return f"{n} line{'s' if n != 1 else ''}, {qty:g} units"


HEADER = ["contact", "party_id", "schedule_date", "source_location_id", "dest_location_id"]


@router.get("/contacts")
def contacts(type: str | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Previously used contacts, so they can be picked instead of retyped."""
    stmt = select(Operation.contact).where(Operation.contact.isnot(None), Operation.contact != "Inventory Adjustment").distinct().limit(1000)
    if type:
        stmt = stmt.where(Operation.type == type)
    return sorted(c for c in db.scalars(stmt) if c.strip())


# ------------------------------------------------------------------ list
def operations_page(
    db: Session, *, type=None, status=None, q=None, warehouse_id=None, location_id=None, category_id=None, page: PageParams | None = None
):
    """Documents newest first. With `page` this returns the paged envelope, otherwise the full list."""
    base = op_filters(
        select(Operation), type=type, status=status, warehouse_id=warehouse_id, location_id=location_id, category_id=category_id, q=q
    )
    stmt = base.options(
        selectinload(Operation.lines),
        joinedload(Operation.party),
        joinedload(Operation.warehouse),
        joinedload(Operation.responsible),
        joinedload(Operation.source_location).joinedload(Location.warehouse),
        joinedload(Operation.dest_location).joinedload(Location.warehouse),
    ).order_by(Operation.id.desc())
    if page is None or not page.enabled:
        return [op_out(db, o, with_lines=False) for o in db.scalars(stmt)]
    total = count_rows(db, base)
    return envelope([op_out(db, o, with_lines=False) for o in db.scalars(slice_stmt(stmt, page))], total, page)


@router.get("/operations")
def list_operations(
    type: str | None = None,
    status: str | None = None,
    q: str | None = None,
    warehouse_id: int | None = None,
    location_id: int | None = None,
    category_id: int | None = None,
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    return operations_page(db, type=type, status=status, q=q, warehouse_id=warehouse_id, location_id=location_id,
                           category_id=category_id, page=page)


# ------------------------------------------------------------------ create / read / update
@router.post("/operations", status_code=201)
def create_operation(body: OperationIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.type not in ("IN", "OUT", "INT"):
        raise HTTPException(422, "Type must be IN, OUT or INT (use Stock > Update for adjustments)")
    ensure_can_edit_docs(user, body.type)
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
    db.flush()
    audit.record(db, user, "create", "operation", op.id, op.reference, detail=_lines_summary(op.lines))
    db.commit()
    return op_out(db, _load(db, op.id))


@router.get("/operations/{op_id}")
def get_operation(op_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return op_out(db, _load(db, op_id))


@router.get("/operations/{op_id}/history")
def operation_history(op_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Who did what to this document, newest first."""
    if not db.get(Operation, op_id):
        raise HTTPException(404, "Record not found")
    return audit.history(db, "operation", op_id)


@router.put("/operations/{op_id}")
def update_operation(op_id: int, body: OperationIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    op = _load(db, op_id)
    ensure_can_edit_docs(user, op.type)
    check_version(op, body.version)
    if op.status not in ("draft", "waiting", "ready"):
        raise HTTPException(409, "Finished records cannot be edited")
    _validate_lines(db, body.lines)
    before = audit.snapshot(op, HEADER)
    lines_before = _lines_summary(op.lines)
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
    stock.touch(op)
    changes = audit.diff(before, audit.snapshot(op, HEADER))
    if (after := _lines_summary(op.lines)) != lines_before:
        changes["lines"] = [lines_before, after]
    audit.record(db, user, "update", "operation", op.id, op.reference, changes=changes or None)
    db.commit()
    return op_out(db, _load(db, op_id))


# ------------------------------------------------------------------ workflow actions
def _commit_or_conflict(db: Session) -> None:
    """The database refuses negative stock. If two people raced for the last units, the loser gets a clear 409."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, NOT_ENOUGH)


@router.post("/operations/{op_id}/{action}")
def operation_action(
    op_id: int,
    action: str,
    body: ValidateIn | None = None,
    version: int | None = Query(None, description="the version the client is looking at (optimistic locking)"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    op = _load(db, op_id)
    check_version(op, version)
    message = None
    if action in ("duplicate", "cancel"):
        ensure_can_edit_docs(user, op.type)  # anyone may work a document through its stages; changing it needs the right role
    if action == "duplicate":
        if op.type == "ADJ":
            raise HTTPException(409, "Adjustments cannot be duplicated")
        party = op.party if op.party and op.party.active else None
        copy = Operation(
            reference=stock.next_reference(db, op.warehouse, op.type), type=op.type, status="draft",
            contact=party.name if party else op.contact, party_id=party.id if party else None,
            schedule_date=date.today(), responsible_id=user.id, warehouse_id=op.warehouse_id,
            source_location_id=op.source_location_id, dest_location_id=op.dest_location_id,
        )
        copy.lines = _make_lines(db, [LineIn(product_id=l.product_id, quantity=l.quantity) for l in op.lines], op.type)
        db.add(copy)
        db.flush()
        audit.record(db, user, "duplicate", "operation", op.id, op.reference, detail=f"copied to {copy.reference}")
        audit.record(db, user, "create", "operation", copy.id, copy.reference, detail=f"copy of {op.reference}")
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
    except IntegrityError:  # the stock move itself tripped the non-negative rule: someone else took the units first
        db.rollback()
        raise HTTPException(409, NOT_ENOUGH)
    audit.record(db, user, action, "operation", op.id, op.reference, detail=message or f"now {op.status}")
    _commit_or_conflict(db)
    out = op_out(db, _load(db, op_id))
    out["message"] = message
    return out


# ------------------------------------------------------------------ move history (one row per product line)
def moves_page(
    db: Session, *, q=None, status=None, direction=None, type=None, warehouse_id=None, location_id=None, category_id=None,
    page: PageParams | None = None,
):
    """Drafts and cancelled records are not moves yet. Filtering, ordering and paging all happen in SQL."""
    src, dst = aliased(Location), aliased(Location)
    swh, dwh = aliased(Warehouse), aliased(Warehouse)
    from_name = case((src.warehouse_id.isnot(None), func.concat(swh.short_code, "/", src.short_code)), else_=src.name)
    to_name = case((dst.warehouse_id.isnot(None), func.concat(dwh.short_code, "/", dst.short_code)), else_=dst.name)
    stmt = (
        select(
            Operation.id.label("op_id"), Operation.reference, Operation.type, Operation.contact, Operation.status,
            Operation.schedule_date, Operation.done_at, OperationLine.quantity, Product.sku, Product.name.label("pname"),
            src.type.label("src_type"), dst.type.label("dst_type"), from_name.label("from_name"), to_name.label("to_name"),
        )
        .select_from(Operation)
        .join(OperationLine, OperationLine.operation_id == Operation.id)
        .join(Product, Product.id == OperationLine.product_id)
        .join(src, src.id == Operation.source_location_id)
        .join(dst, dst.id == Operation.dest_location_id)
        .outerjoin(swh, swh.id == src.warehouse_id)
        .outerjoin(dwh, dwh.id == dst.warehouse_id)
        .where(Operation.status.notin_(["draft", "cancelled"]))
        .order_by(Operation.id.desc(), OperationLine.id)
    )
    stmt = op_filters(stmt, type=type, status=status, warehouse_id=warehouse_id, location_id=location_id, category_id=category_id)
    if q:
        like = f"%{q}%"  # a document match keeps all its lines; a product match shows just that product's line
        stmt = stmt.where(or_(Operation.reference.ilike(like), Operation.contact.ilike(like), Product.name.ilike(like), Product.sku.ilike(like)))
    is_in = and_(dst.type == "internal", src.type != "internal")
    is_out = and_(src.type == "internal", dst.type != "internal")
    if direction == "in":
        stmt = stmt.where(is_in)
    elif direction == "out":
        stmt = stmt.where(is_out)
    elif direction == "transfer":
        stmt = stmt.where(not_(or_(is_in, is_out)))

    def shape(r) -> dict:
        d = "in" if (r.dst_type == "internal" and r.src_type != "internal") else "out" if (r.src_type == "internal" and r.dst_type != "internal") else "transfer"
        when = r.done_at.date() if r.done_at else r.schedule_date
        return {
            "operation_id": r.op_id, "reference": r.reference, "type": r.type, "contact": r.contact, "status": r.status,
            "date": when.isoformat() if when else None, "from": r.from_name, "to": r.to_name,
            "product": f"[{r.sku}] {r.pname}", "quantity": float(r.quantity), "direction": d,
        }

    if page is None or not page.enabled:
        return [shape(r) for r in db.execute(stmt)]
    return envelope([shape(r) for r in db.execute(slice_stmt(stmt, page))], count_rows(db, stmt), page)


@router.get("/moves")
def move_history(
    q: str | None = None,
    status: str | None = None,
    direction: str | None = None,
    type: str | None = None,
    warehouse_id: int | None = None,
    location_id: int | None = None,
    category_id: int | None = None,
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    return moves_page(db, q=q, status=status, direction=direction, type=type, warehouse_id=warehouse_id,
                      location_id=location_id, category_id=category_id, page=page)
