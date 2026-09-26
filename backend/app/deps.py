"""Who is calling, and what may they do.

Roles, lowest to highest:
  staff    warehouse staff: see everything; run internal transfers; pick, pack and validate; count stock
  manager  inventory manager: also create/edit/cancel receipts and deliveries, products, contacts; import; reorder
  admin    everything, plus warehouses, locations, taxes, users and the activity log
"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .security import decode_token

bearer = HTTPBearer(auto_error=False)

RANK = {"staff": 1, "manager": 2, "admin": 3}
ROLES = tuple(RANK)


def current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> User:
    uid = decode_token(cred.credentials) if cred else None
    user = db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(401, "Not authenticated")
    if not user.active:
        raise HTTPException(401, "This account has been deactivated")  # also invalidates tokens issued earlier
    return user


def has_role(user: User, role: str) -> bool:
    return RANK.get(user.role, 0) >= RANK[role]


def require(role: str):
    """Dependency factory: `Depends(require("manager"))` lets managers and admins through, everyone else gets a 403."""

    def dep(user: User = Depends(current_user)) -> User:
        if not has_role(user, role):
            raise HTTPException(403, f"You don't have permission to do that. It needs the {role} role.")
        return user

    return dep


manager = require("manager")
admin = require("admin")


def ensure_can_edit_docs(user: User, op_type: str) -> None:
    """Warehouse staff may work on internal transfers; receipts and deliveries need a manager."""
    if op_type == "INT":
        return
    if not has_role(user, "manager"):
        raise HTTPException(403, "You don't have permission to change receipts and deliveries. It needs the manager role.")
