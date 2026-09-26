"""Suppliers and customers, with GSTIN validation and per-party history."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import Session

from .. import audit, lifecycle
from ..conflict import bump, check_version
from ..db import get_db
from ..deps import current_user, manager
from ..models import Operation, OperationLine, Party, User
from ..pagination import PageParams, count_rows, envelope, slice_stmt

router = APIRouter(tags=["parties"], dependencies=[Depends(current_user)])

KINDS = ("vendor", "customer", "both")
TRACKED = ["name", "kind", "gstin", "email", "phone", "address"]

# GST state / UT codes (the first two digits of a GSTIN)
STATES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura",
    "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh",
    "23": "Madhya Pradesh", "24": "Gujarat", "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman & Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}
GSTIN_RE = re.compile(r"^(\d{2})([A-Z]{5}\d{4}[A-Z])([1-9A-Z])Z([0-9A-Z])$")
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_char(first14: str) -> str:
    """The 15th character of a GSTIN is a mod-36 check digit over the first 14."""
    factor, total = 2, 0
    for ch in reversed(first14):
        digit = factor * _CHARS.index(ch)
        total += digit // 36 + digit % 36
        factor = 1 if factor == 2 else 2
    return _CHARS[(36 - total % 36) % 36]


def validate_gstin(raw: str | None) -> str | None:
    g = (raw or "").strip().upper()
    if not g:
        return None
    m = GSTIN_RE.match(g)
    if not m:
        raise HTTPException(422, "GSTIN must be 15 characters, like 24AAACC1206D1ZM")
    if m.group(1) not in STATES:
        raise HTTPException(422, f"GSTIN starts with an unknown state code ({m.group(1)})")
    if gstin_check_char(g[:14]) != g[14]:
        raise HTTPException(422, "GSTIN check digit is wrong - please re-check the number")
    return g


class PartyIn(BaseModel):
    name: str = Field(max_length=150)
    kind: str = Field(default="both", max_length=10)
    gstin: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=300)
    version: int | None = None  # the version the editor loaded, for optimistic locking

    @field_validator("email", "gstin", "phone", "address", mode="before")
    @classmethod
    def blank_to_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


def party_out(p: Party, stats: dict | None = None) -> dict:
    s = stats or {}
    return {
        "id": p.id,
        "name": p.name,
        "kind": p.kind,
        "gstin": p.gstin,
        "state": STATES.get(p.gstin[:2]) if p.gstin else None,
        "email": p.email,
        "phone": p.phone,
        "address": p.address,
        "active": p.active,
        "version": p.version,
        "documents": s.get("documents", 0),
        "total_value": round(s.get("total", 0), 2),
        "last_document": s.get("last").isoformat() if s.get("last") else None,
    }


def brief(p: Party) -> dict:
    """The compact form embedded in a document."""
    return {"id": p.id, "name": p.name, "kind": p.kind, "gstin": p.gstin, "address": p.address, "email": p.email,
            "phone": p.phone, "state": STATES.get(p.gstin[:2]) if p.gstin else None}


def _stats(db: Session, ids: list[int] | None = None) -> dict[int, dict]:
    stmt = (
        select(
            Operation.party_id,
            func.count(distinct(Operation.id)),
            func.coalesce(func.sum(OperationLine.quantity * OperationLine.unit_price * (1 + OperationLine.tax_rate / 100)), 0),
            func.max(Operation.schedule_date),
        )
        .join(OperationLine, OperationLine.operation_id == Operation.id)
        .where(Operation.party_id.isnot(None), Operation.status != "cancelled")
        .group_by(Operation.party_id)
    )
    if ids is not None:
        if not ids:
            return {}
        stmt = stmt.where(Operation.party_id.in_(ids))
    return {pid: {"documents": n, "total": float(t), "last": d} for pid, n, t, d in db.execute(stmt).all()}


def _clean(body: PartyIn) -> tuple[str, str]:
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Name is required")
    if body.kind not in KINDS:
        raise HTTPException(422, "Type must be vendor, customer or both")
    return name, body.kind


@router.get("/parties")
def list_parties(
    q: str | None = None,
    kind: str | None = None,
    include_archived: bool = False,
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
):
    base = select(Party)
    if not include_archived:
        base = base.where(Party.active.is_(True))
    if kind in ("vendor", "customer"):
        base = base.where(Party.kind.in_([kind, "both"]))
    if q:
        like = f"%{q}%"
        base = base.where(or_(Party.name.ilike(like), Party.gstin.ilike(like), Party.email.ilike(like)))
    stmt = base.order_by(Party.name)
    if not page.enabled:
        rows = list(db.scalars(stmt))
        stats = _stats(db)
        return [party_out(p, stats.get(p.id)) for p in rows]
    rows = list(db.scalars(slice_stmt(stmt, page)))
    stats = _stats(db, [p.id for p in rows])  # history for just the 25 on screen, not the whole book
    return envelope([party_out(p, stats.get(p.id)) for p in rows], count_rows(db, base), page)


@router.post("/parties", status_code=201)
def create_party(body: PartyIn, db: Session = Depends(get_db), actor: User = Depends(manager)):
    name, kind = _clean(body)
    if db.scalar(select(Party).where(func.lower(Party.name) == name.lower())):
        raise HTTPException(409, "A contact with this name already exists")
    p = Party(name=name, kind=kind, gstin=validate_gstin(body.gstin), email=body.email, phone=body.phone, address=body.address)
    db.add(p)
    db.flush()
    audit.record(db, actor, "create", "contact", p.id, p.name)
    db.commit()
    return party_out(p)


@router.get("/parties/{pid}")
def get_party(pid: int, db: Session = Depends(get_db)):
    p = db.get(Party, pid)
    if not p:
        raise HTTPException(404, "Contact not found")
    ops = db.scalars(select(Operation).where(Operation.party_id == pid).order_by(Operation.id.desc()).limit(10)).all()
    from .operations import op_out  # local import: operations imports this module

    out = party_out(p, _stats(db, [pid]).get(pid))
    out["recent"] = [op_out(db, o, with_lines=False) for o in ops]
    return out


@router.put("/parties/{pid}")
def update_party(pid: int, body: PartyIn, db: Session = Depends(get_db), actor: User = Depends(manager)):
    p = db.get(Party, pid)
    if not p:
        raise HTTPException(404, "Contact not found")
    check_version(p, body.version)
    name, kind = _clean(body)
    if db.scalar(select(Party).where(func.lower(Party.name) == name.lower(), Party.id != pid)):
        raise HTTPException(409, "A contact with this name already exists")
    old = audit.snapshot(p, TRACKED)
    p.name, p.kind, p.gstin = name, kind, validate_gstin(body.gstin)
    p.email, p.phone, p.address = body.email, body.phone, body.address
    if changes := audit.diff(old, audit.snapshot(p, TRACKED)):
        bump(p)
        audit.record(db, actor, "update", "contact", p.id, p.name, changes=changes)
    db.commit()
    return party_out(p, _stats(db, [pid]).get(pid))


@router.post("/parties/{pid}/archive")
def archive_party(pid: int, db: Session = Depends(get_db), actor: User = Depends(manager)):
    p = db.get(Party, pid)
    if not p:
        raise HTTPException(404, "Contact not found")
    if reason := lifecycle.archive_blocker(lifecycle.party_usage(db, pid), "This contact"):
        raise HTTPException(409, reason)
    p.active = False
    bump(p)
    audit.record(db, actor, "archive", "contact", p.id, p.name)
    db.commit()
    return party_out(p)


@router.post("/parties/{pid}/restore")
def restore_party(pid: int, db: Session = Depends(get_db), actor: User = Depends(manager)):
    p = db.get(Party, pid)
    if not p:
        raise HTTPException(404, "Contact not found")
    p.active = True
    bump(p)
    audit.record(db, actor, "restore", "contact", p.id, p.name)
    db.commit()
    return party_out(p)


@router.delete("/parties/{pid}")
def delete_party(pid: int, db: Session = Depends(get_db), actor: User = Depends(manager)):
    p = db.get(Party, pid)
    if not p:
        raise HTTPException(404, "Contact not found")
    if reason := lifecycle.delete_blocker(lifecycle.party_usage(db, pid), "This contact"):
        raise HTTPException(409, reason)
    audit.record(db, actor, "delete", "contact", pid, p.name)
    db.delete(p)
    db.commit()
    return {"ok": True}
