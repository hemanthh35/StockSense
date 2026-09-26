"""Audit trail: who did what, when, and what changed. Written in the same transaction as the change itself,
so a rolled-back change leaves no trace and a committed one always has one."""
import json
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .models import Base, User
from .stock import utcnow


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_entity", "entity", "entity_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    user_login: Mapped[str | None] = mapped_column(String(50))  # kept even if the user is later removed
    action: Mapped[str] = mapped_column(String(30), index=True)
    entity: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(200))  # reference / name, for humans
    changes: Mapped[str | None] = mapped_column(Text)  # JSON {field: [old, new]}
    detail: Mapped[str | None] = mapped_column(String(300))


def record(
    db: Session,
    user: User | None,
    action: str,
    entity: str,
    entity_id: int | None = None,
    label: str | None = None,
    changes: dict | None = None,
    detail: str | None = None,
) -> None:
    """Queue an audit row on the current session; it is committed together with the change."""
    db.add(AuditLog(
        user_id=user.id if user else None,
        user_login=user.login_id if user else None,
        action=action, entity=entity, entity_id=entity_id, label=(label or "")[:200] or None,
        changes=json.dumps(changes, default=str)[:4000] if changes else None,
        detail=(detail or "")[:300] or None,
    ))


def snapshot(obj, fields: list[str]) -> dict:
    return {f: getattr(obj, f) for f in fields}


def diff(old: dict, new: dict) -> dict:
    """{field: [before, after]} for every field that really changed (numbers compared as numbers)."""
    out = {}
    for k, v in new.items():
        o = old.get(k)
        same = (float(o) == float(v)) if isinstance(o, (int, float)) and isinstance(v, (int, float)) else (o == v)
        if not same:
            out[k] = [o, v]
    return out


def row_out(a: AuditLog) -> dict:
    return {
        "id": a.id,
        "at": a.at.isoformat() + "Z",
        "user": a.user_login,
        "action": a.action,
        "entity": a.entity,
        "entity_id": a.entity_id,
        "label": a.label,
        "changes": json.loads(a.changes) if a.changes else None,
        "detail": a.detail,
    }


def history(db: Session, entity: str, entity_id: int, limit: int = 100) -> list[dict]:
    stmt = (
        select(AuditLog).where(AuditLog.entity == entity, AuditLog.entity_id == entity_id)
        .order_by(AuditLog.id.desc()).limit(limit)
    )
    return [row_out(a) for a in db.scalars(stmt)]
