"""User administration and the activity log."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit
from ..audit import AuditLog
from ..db import get_db
from ..deps import ROLES, admin, manager
from ..models import User
from ..pagination import PageParams, count_rows, envelope, slice_stmt

router = APIRouter(tags=["users"])


class UserUpdate(BaseModel):
    role: str = Field(max_length=10)
    active: bool = True


def full_out(u: User) -> dict:
    return {"id": u.id, "login_id": u.login_id, "email": u.email, "role": u.role, "active": u.active,
            "created_at": u.created_at.isoformat() if u.created_at else None}


@router.get("/users")
def list_users(page: PageParams = Depends(), db: Session = Depends(get_db), _: User = Depends(admin)):
    page.page = page.page or 1
    stmt = select(User).order_by(User.id)
    return envelope([full_out(u) for u in db.scalars(slice_stmt(stmt, page))], count_rows(db, stmt), page)


@router.put("/users/{uid}")
def update_user(uid: int, body: UserUpdate, db: Session = Depends(get_db), actor: User = Depends(admin)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    if body.role not in ROLES:
        raise HTTPException(422, f"Role must be one of: {', '.join(ROLES)}")
    losing_admin = u.role == "admin" and u.active and (body.role != "admin" or not body.active)
    if losing_admin:
        other = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.active.is_(True), User.id != u.id)) or 0
        if not other:
            raise HTTPException(409, "There must always be at least one active administrator")
    changes = audit.diff({"role": u.role, "active": u.active}, {"role": body.role, "active": body.active})
    u.role, u.active = body.role, body.active
    if changes:
        audit.record(db, actor, "role" if "role" in changes else "update", "user", u.id, u.login_id, changes=changes)
    db.commit()
    return full_out(u)


@router.get("/audit")
def audit_log(
    q: str | None = None,
    entity: str | None = None,
    action: str | None = None,
    user: str | None = None,
    entity_id: int | None = None,
    page: PageParams = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(manager),
):
    """Newest first. Managers and administrators may read it."""
    page.page = page.page or 1
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user:
        stmt = stmt.where(AuditLog.user_login == user)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(AuditLog.label.ilike(like), AuditLog.user_login.ilike(like), AuditLog.detail.ilike(like)))
    return envelope([audit.row_out(a) for a in db.scalars(slice_stmt(stmt, page))], count_rows(db, stmt), page)
