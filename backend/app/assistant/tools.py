"""What the assistant may do. Every tool is a thin wrapper over code the normal API already uses, so validation,
roles, stock rules and the audit log apply exactly as they do for a person clicking in the UI.

* READ tools run immediately and return small, plain data (no emails, phone numbers or other personal fields).
* WRITE tools never change anything when the model calls them. They validate the request, turn names into ids and
  return a *proposal*; the person confirms it in the UI and only then does `execute` run (see service.py).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..deps import has_role
from ..models import Location, Operation, OperationLine, Party, Product, User, Warehouse
from ..pagination import PageParams
from ..queries import incoming_map
from ..routers import inventory, operations, reports

TYPE_CODES = {"receipt": "IN", "receipts": "IN", "in": "IN", "delivery": "OUT", "deliveries": "OUT", "out": "OUT",
              "transfer": "INT", "transfers": "INT", "internal": "INT", "int": "INT",
              "adjustment": "ADJ", "adjustments": "ADJ", "adj": "ADJ"}
OPEN = ("draft", "waiting", "ready")
ACTIONS = ("todo", "check", "pick", "pack", "validate", "cancel")


class ToolError(Exception):
    """Something the model can fix or explain (unknown product, not allowed...). Sent back to it as the tool result."""


@dataclass
class Ctx:
    db: Session
    user: User


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    role: str = "staff"
    run: Callable[[Ctx, dict], dict] | None = None  # read tools
    prepare: Callable[[Ctx, dict], tuple[dict, str]] | None = None  # write tools: -> (canonical args, one-line summary)
    execute: Callable[[Ctx, dict], dict] | None = None  # write tools: runs only after the person confirms
    keys: list[str] = field(default_factory=list)

    @property
    def writes(self) -> bool:
        return self.prepare is not None

    def spec(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


S = {"type": "string"}
LINES = {"type": "array", "minItems": 1, "maxItems": 50, "items": _obj(
    {"product": {**S, "description": "SKU (preferred) or product name"}, "quantity": {"type": "number"},
     "unit_price": {"type": "number", "description": "optional; defaults to the product's price"}}, ["product", "quantity"])}


# ------------------------------------------------------------------ name -> record resolvers
def find_product(db: Session, text: str) -> Product:
    text = (text or "").strip()
    if not text:
        raise ToolError("A product name or SKU is required.")
    base = select(Product).where(Product.active.is_(True))
    exact = db.scalars(base.where(func.lower(Product.sku) == text.lower())).all()
    if not exact:
        exact = db.scalars(base.where(func.lower(Product.name) == text.lower())).all()
    if len(exact) == 1:
        return exact[0]
    found = exact or db.scalars(base.where(or_(Product.name.ilike(f"%{text}%"), Product.sku.ilike(f"%{text}%"))).order_by(Product.name).limit(6)).all()
    if not found:
        raise ToolError(f"No product matches '{text}'. Use search_products to look for it.")
    if len(found) == 1:
        return found[0]
    raise ToolError(f"'{text}' matches several products: " + "; ".join(f"{p.sku} ({p.name})" for p in found) + ". Ask which one, or use the SKU.")


def find_location(db: Session, text: str) -> Location:
    text = (text or "").strip().lower()
    locs = db.scalars(select(Location).join(Warehouse, Warehouse.id == Location.warehouse_id)
                      .where(Location.type == "internal", Location.active.is_(True))).all()
    hits = [l for l in locs if l.full_name.lower() == text] or [l for l in locs if text and text in l.full_name.lower()]
    if len(hits) == 1:
        return hits[0]
    names = ", ".join(l.full_name for l in locs[:12])
    if not hits:
        raise ToolError(f"No stock location matches '{text}'. Locations: {names}")
    raise ToolError(f"'{text}' matches several locations: " + ", ".join(l.full_name for l in hits[:8]) + ". Use the full name.")


def find_warehouse(db: Session, text: str | None) -> Warehouse | None:
    if not text:
        return None
    t = text.strip().lower()
    whs = db.scalars(select(Warehouse).where(Warehouse.active.is_(True))).all()
    hits = [w for w in whs if t in (w.short_code.lower(), w.name.lower())] or [w for w in whs if t in w.name.lower()]
    if len(hits) != 1:
        raise ToolError(f"No single warehouse matches '{text}'. Warehouses: " + ", ".join(f"{w.short_code} ({w.name})" for w in whs))
    return hits[0]


def find_party(db: Session, name: str | None) -> tuple[int | None, str | None]:
    """A saved contact wins; otherwise the text is kept as a plain contact name, like typing it into the form."""
    if not name or not name.strip():
        return None, None
    name = name.strip()
    p = db.scalar(select(Party).where(func.lower(Party.name) == name.lower(), Party.active.is_(True)))
    if not p:
        ps = db.scalars(select(Party).where(Party.name.ilike(f"%{name}%"), Party.active.is_(True)).limit(2)).all()
        p = ps[0] if len(ps) == 1 else None
    return (p.id, p.name) if p else (None, name)


def _lines(db: Session, raw: list[dict]) -> tuple[list[dict], list[str]]:
    if not isinstance(raw, list) or not raw:
        raise ToolError("At least one line is required.")
    lines, texts = [], []
    for ln in raw:
        try:
            qty = float(ln.get("quantity"))
        except (TypeError, ValueError):
            raise ToolError("Each line needs a numeric quantity.")
        if qty <= 0:
            raise ToolError("Quantities must be greater than zero.")
        p = find_product(db, str(ln.get("product", "")))
        item = {"product_id": p.id, "quantity": qty}
        if ln.get("unit_price") is not None:
            item["unit_price"] = float(ln["unit_price"])
        lines.append(item)
        texts.append(f"{qty:g} × {p.name} ({p.sku})")
    return lines, texts


# ------------------------------------------------------------------ read tools
def _p(page_size: int) -> PageParams:
    return PageParams(page=1, page_size=max(1, min(int(page_size or 10), 20)))


def t_search_products(c: Ctx, a: dict) -> dict:
    page = inventory.stock_rows(c.db, q=a.get("query"), page=_p(a.get("limit", 10)))
    incoming = incoming_map(c.db, None, [r["product_id"] for r in page["items"]])
    return {"total_matches": page["total"], "products": [
        {"sku": r["sku"], "name": r["name"], "category": r["category"], "on_hand": r["on_hand"], "free_to_use": r["free_to_use"],
         "incoming": incoming.get(r["product_id"], 0), "reorder_min": r["reorder_min"], "low_stock": r["low_stock"], "sales_price": r["unit_cost"]}
        for r in page["items"]]}


def t_get_product_stock(c: Ctx, a: dict) -> dict:
    p = find_product(c.db, a.get("product", ""))
    row = next(r for r in inventory.stock_rows(c.db, q=p.sku) if r["product_id"] == p.id)
    return {"sku": p.sku, "name": p.name, "on_hand": row["on_hand"], "free_to_use": row["free_to_use"], "reorder_min": p.reorder_min,
            "reorder_qty": p.reorder_qty, "incoming": incoming_map(c.db, None, [p.id]).get(p.id, 0), "purchase_cost": p.avg_cost or p.cost_price,
            "sales_price": p.unit_cost, "locations": [{"location": l["location"], "on_hand": l["on_hand"], "free": l["free_to_use"]} for l in row["locations"]]}


def t_low_stock(c: Ctx, a: dict) -> dict:
    items = inventory._suggestions(c.db, None)
    return {"count": len(items), "products": [
        {"sku": i["sku"], "name": i["name"], "on_hand": i["on_hand"], "incoming": i["incoming"], "reorder_min": i["reorder_min"], "suggested_order_qty": i["suggested_qty"]}
        for i in items[:20]]}


def _brief(o: dict) -> dict:
    keys = ("reference", "type_label", "status", "contact", "schedule_date", "late", "total", "warehouse")
    out = {k: o.get(k) for k in keys}
    out["warehouse"] = (o.get("warehouse") or {}).get("short_code")
    return out


def t_list_documents(c: Ctx, a: dict) -> dict:
    kind = TYPE_CODES.get(str(a.get("type", "")).lower()) if a.get("type") else None
    if a.get("type") and not kind:
        raise ToolError("type must be receipt, delivery, transfer or adjustment.")
    limit = max(1, min(int(a.get("limit", 10) or 10), 20))
    late = bool(a.get("late_only"))
    page = operations.operations_page(c.db, type=kind, status=a.get("status"), q=a.get("search"), page=_p(50 if late else limit))
    items = [o for o in page["items"] if o["late"]] if late else page["items"]
    return {"total_matches": page["total"], "documents": [_brief(o) for o in items[:limit]]}


def _get_op(db: Session, ref: str) -> Operation:
    op = db.scalar(select(Operation).where(func.lower(Operation.reference) == (ref or "").strip().lower()))
    if not op:
        raise ToolError(f"No document with reference '{ref}'.")
    return op


def t_get_document(c: Ctx, a: dict) -> dict:
    o = operations.op_out(c.db, operations._load(c.db, _get_op(c.db, a.get("reference", "")).id))
    out = _brief(o)
    out.update(source=o["source_location"]["name"], destination=o["dest_location"]["name"], responsible=o["responsible"], picked=o["picked"], packed=o["packed"])
    out["lines"] = [{"product": l["product"], "quantity": l["quantity"], "ordered": l["ordered_qty"], "unit_price": l["unit_price"],
                     "short_by": l["missing"] if l["short"] else 0} for l in o["lines"]]
    return out


def t_dashboard_summary(c: Ctx, a: dict) -> dict:
    d = inventory.dashboard(doc_type=None, status=None, warehouse_id=None, location_id=None, category_id=None, db=c.db, _=c.user)
    return {"kpis": d["kpis"], "reorder_suggestions": d["reorder_count"],
            "documents": [{"type": x["type"], "to_process": x["to_process"], "late": x["late"], "waiting": x["waiting"]} for x in d["cards"]],
            "worst_low_stock": [{"sku": i["sku"], "name": i["name"], "on_hand": i["on_hand"]} for i in d["low_stock_items"][:5]]}


def t_find_incoming(c: Ctx, a: dict) -> dict:
    p = find_product(c.db, a.get("product", ""))
    rows = c.db.execute(
        select(Operation.reference, Operation.status, Operation.schedule_date, Operation.contact, OperationLine.quantity)
        .join(OperationLine, OperationLine.operation_id == Operation.id)
        .where(OperationLine.product_id == p.id, Operation.type == "IN", Operation.status.in_(OPEN)).order_by(Operation.schedule_date)
    ).all()
    return {"product": f"{p.sku} {p.name}", "incoming_total": sum(float(r[4]) for r in rows), "receipts": [
        {"reference": r[0], "status": r[1], "expected": r[2].isoformat() if r[2] else None, "supplier": r[3], "quantity": float(r[4])} for r in rows]}


def t_business_report(c: Ctx, a: dict) -> dict:
    kind = a.get("kind", "valuation")
    if kind == "margin":
        r = reports.margin_rows(c.db, max(1, min(int(a.get("days", 30) or 30), 365)), None, None)
        return {"kind": "margin", "days": a.get("days", 30), "totals": r["totals"], "top_products": r["rows"][:10]}
    if kind != "valuation":
        raise ToolError("kind must be 'valuation' or 'margin'.")
    r = reports.valuation_rows(c.db, None, None, None, None, False)
    return {"kind": "valuation", "totals": r["totals"], "by_category": r.get("by_category"), "top_products": r["rows"][:10]}


def t_stock_forecast(c: Ctx, a: dict) -> dict:
    r = reports.forecast_rows(c.db, max(7, min(int(a.get("days", 30) or 30), 365)))
    return {"based_on_days": r["days"], "counts": r["counts"], "soonest_to_run_out": [
        {k: x[k] for k in ("sku", "name", "on_hand", "incoming", "per_day", "days_left", "runs_out_on", "level")} for x in r["rows"][:12]]}


def t_expiring_stock(c: Ctx, a: dict) -> dict:
    from ..routers.lots import lots_page
    days = max(1, min(int(a.get("days", 30) or 30), 365))
    rows = lots_page(c.db, days=days, status=a.get("status") or "soon", page=_p(15))
    from .. import lots as lots_mod
    return {"summary": lots_mod.summary(c.db, days), "lots": [
        {k: x[k] for k in ("sku", "name", "lot_no", "expiry_date", "days_left", "remaining", "value")} for x in rows["items"]]}


def t_list_contacts(c: Ctx, a: dict) -> dict:
    stmt = select(Party).where(Party.active.is_(True)).order_by(Party.name).limit(15)
    if a.get("query"):
        stmt = stmt.where(Party.name.ilike(f"%{a['query']}%"))
    if a.get("kind") in ("vendor", "customer"):
        stmt = stmt.where(Party.kind.in_((a["kind"], "both")))
    return {"contacts": [{"name": p.name, "kind": p.kind, "gstin": p.gstin} for p in c.db.scalars(stmt)]}


# ------------------------------------------------------------------ write tools: prepare (validate + describe) / execute
def _doc_prepare(op_type: str, party_key: str, noun: str):
    def prepare(c: Ctx, a: dict) -> tuple[dict, str]:
        lines, texts = _lines(c.db, a.get("lines"))
        wh = find_warehouse(c.db, a.get("warehouse"))
        party_id, contact = find_party(c.db, a.get(party_key))
        canon = {"type": op_type, "lines": lines, "warehouse_id": wh.id if wh else None, "party_id": party_id,
                 "contact": None if party_id else contact, "schedule_date": a.get("schedule_date")}
        who = f" {'from' if op_type == 'IN' else 'for'} {contact}" if contact else ""
        return canon, f"Create a draft {noun}{who}{' in ' + wh.short_code if wh else ''}: " + ", ".join(texts)
    return prepare


def _prepare_transfer(c: Ctx, a: dict) -> tuple[dict, str]:
    lines, texts = _lines(c.db, a.get("lines"))
    src, dst = find_location(c.db, a.get("from_location")), find_location(c.db, a.get("to_location"))
    if src.id == dst.id:
        raise ToolError("The source and destination are the same location.")
    canon = {"type": "INT", "lines": lines, "source_location_id": src.id, "dest_location_id": dst.id, "schedule_date": a.get("schedule_date")}
    return canon, f"Create a draft transfer {src.full_name} → {dst.full_name}: " + ", ".join(texts)


def _execute_document(c: Ctx, args: dict) -> dict:
    try:
        body = operations.OperationIn(**args)
    except ValidationError as e:
        raise ToolError("Invalid document: " + "; ".join(x["msg"] for x in e.errors()[:3]))
    out = operations.create_operation(body, c.db, c.user)
    return {"reference": out["reference"], "id": out["id"], "type": out["type"], "status": out["status"], "total": out.get("total")}


def _prepare_reorder(c: Ctx, a: dict) -> tuple[dict, str]:
    wh = find_warehouse(c.db, a.get("warehouse"))
    items = inventory._suggestions(c.db, wh.id if wh else None)
    if not items:
        raise ToolError("Nothing needs reordering right now.")
    return ({"warehouse_id": wh.id if wh else None},
            f"Create one draft receipt for {len(items)} low-stock product(s): " + ", ".join(f"{i['suggested_qty']:g} × {i['name']}" for i in items[:8]) + ("…" if len(items) > 8 else ""))


def _execute_reorder(c: Ctx, args: dict) -> dict:
    out = inventory.reorder_receipt(inventory.ReorderIn(warehouse_id=args.get("warehouse_id")), c.db, c.user)
    return {"reference": out["reference"], "id": out["id"], "type": "IN", "status": out["status"]}


def _prepare_adjust(c: Ctx, a: dict) -> tuple[dict, str]:
    p, loc = find_product(c.db, a.get("product", "")), find_location(c.db, a.get("location", ""))
    try:
        counted = float(a.get("counted_qty"))
    except (TypeError, ValueError):
        raise ToolError("counted_qty must be a number.")
    if counted < 0:
        raise ToolError("counted_qty can't be negative.")
    before = float(next((q["on_hand"] for r in inventory.stock_rows(c.db, q=p.sku) if r["product_id"] == p.id for q in r["locations"] if q["location_id"] == loc.id), 0))
    return ({"product_id": p.id, "location_id": loc.id, "counted_qty": counted},
            f"Set the stock of {p.name} ({p.sku}) at {loc.full_name} from {before:g} to {counted:g}")


def _execute_adjust(c: Ctx, args: dict) -> dict:
    return inventory.stock_adjust(inventory.AdjustIn(**args), c.db, c.user)


def _prepare_advance(c: Ctx, a: dict) -> tuple[dict, str]:
    op = _get_op(c.db, a.get("reference", ""))
    action = a.get("action")
    if action not in ACTIONS:
        raise ToolError("action must be one of: " + ", ".join(ACTIONS))
    if action in ("cancel",):
        from ..deps import ensure_can_edit_docs
        try:
            ensure_can_edit_docs(c.user, op.type)
        except HTTPException as e:
            raise ToolError(e.detail)
    verb = {"todo": "Mark as ready to process", "check": "Check availability of", "pick": "Mark as picked", "pack": "Mark as packed", "validate": "Validate", "cancel": "Cancel"}[action]
    return {"op_id": op.id, "action": action}, f"{verb} {op.reference} (currently {op.status})"


def _execute_advance(c: Ctx, args: dict) -> dict:
    out = operations.operation_action(args["op_id"], args["action"], None, None, c.db, c.user)
    return {"reference": out["reference"], "id": out["id"], "type": out["type"], "status": out["status"], "message": out.get("message")}


DATE = {**S, "description": "YYYY-MM-DD, optional"}
TOOLS: list[Tool] = [
    Tool("search_products", "Find products by name or SKU with current stock. Empty query lists the first products.",
         _obj({"query": S, "limit": {"type": "integer"}}), run=t_search_products),
    Tool("get_product_stock", "Stock of one product: on hand, free to use, incoming, per location, reorder level.", _obj({"product": S}, ["product"]), run=t_get_product_stock),
    Tool("low_stock", "Products at or below their reorder level with the quantity to order (counts receipts already on the way).", _obj({}), run=t_low_stock),
    Tool("list_documents", "List receipts, deliveries, transfers or adjustments. Filter by type, status (draft/waiting/ready/done/cancelled), search text, or late_only.",
         _obj({"type": S, "status": S, "search": S, "late_only": {"type": "boolean"}, "limit": {"type": "integer"}}), run=t_list_documents),
    Tool("get_document", "One document by reference (e.g. WH/OUT/0003) with its lines and any shortages.", _obj({"reference": S}, ["reference"]), run=t_get_document),
    Tool("dashboard_summary", "Business snapshot: stock value, low/out-of-stock counts, documents to process and late.", _obj({}), run=t_dashboard_summary),
    Tool("find_incoming_stock", "Open receipts that will bring more of a product, with dates and suppliers.", _obj({"product": S}, ["product"]), run=t_find_incoming),
    Tool("business_report", "Stock valuation, or sales margin over the last N days.", _obj({"kind": {"type": "string", "enum": ["valuation", "margin"]}, "days": {"type": "integer"}}, ["kind"]), run=t_business_report),
    Tool("stock_forecast", "Which products will run out soonest at the recent pace of deliveries (days of stock left).", _obj({"days": {"type": "integer", "description": "sales window, default 30"}}), run=t_stock_forecast),
    Tool("expiring_stock", "Batches that expire soon or already expired (status: soon | expired | ok | none).", _obj({"days": {"type": "integer"}, "status": {"type": "string", "enum": ["soon", "expired", "ok", "none"]}}), run=t_expiring_stock),
    Tool("list_contacts", "Saved suppliers and customers (names and GSTIN only).", _obj({"query": S, "kind": {"type": "string", "enum": ["vendor", "customer"]}}), run=t_list_contacts),
    Tool("create_receipt", "PROPOSE a draft receipt (goods coming in). The user must confirm before anything is created.",
         _obj({"supplier": S, "warehouse": S, "schedule_date": DATE, "lines": LINES}, ["lines"]), role="manager",
         prepare=_doc_prepare("IN", "supplier", "receipt"), execute=_execute_document),
    Tool("create_delivery", "PROPOSE a draft delivery (goods going out). The user must confirm before anything is created.",
         _obj({"customer": S, "warehouse": S, "schedule_date": DATE, "lines": LINES}, ["lines"]), role="manager",
         prepare=_doc_prepare("OUT", "customer", "delivery"), execute=_execute_document),
    Tool("create_transfer", "PROPOSE a draft internal transfer between two stock locations (full names like WH/Stock).",
         _obj({"from_location": S, "to_location": S, "schedule_date": DATE, "lines": LINES}, ["from_location", "to_location", "lines"]),
         prepare=_prepare_transfer, execute=_execute_document),
    Tool("reorder_low_stock", "PROPOSE one draft receipt covering everything that needs reordering.", _obj({"warehouse": S}), role="manager",
         prepare=_prepare_reorder, execute=_execute_reorder),
    Tool("adjust_stock", "PROPOSE correcting the counted quantity of a product at a location.",
         _obj({"product": S, "location": S, "counted_qty": {"type": "number"}}, ["product", "location", "counted_qty"]),
         prepare=_prepare_adjust, execute=_execute_adjust),
    Tool("advance_document", "PROPOSE moving a document forward: todo, check, pick, pack, validate, or cancel.",
         _obj({"reference": S, "action": {"type": "string", "enum": list(ACTIONS)}}, ["reference", "action"]),
         prepare=_prepare_advance, execute=_execute_advance),
]
BY_NAME = {t.name: t for t in TOOLS}


def tools_for(user: User) -> list[Tool]:
    return [t for t in TOOLS if has_role(user, t.role)]


def parse_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw or "{}")
    except (TypeError, ValueError):
        raise ToolError("The arguments were not valid JSON.")
    if not isinstance(val, dict):
        raise ToolError("The arguments must be a JSON object.")
    return val


def today() -> str:
    return date.today().isoformat()
