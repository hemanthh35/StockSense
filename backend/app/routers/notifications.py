from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import digest as digest_mod
from .. import mail
from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..models import User

router = APIRouter(prefix="/notifications", tags=["notifications"])


class PrefsIn(BaseModel):
    low_stock_digest: bool


def _prefs(user: User) -> dict:
    return {
        "low_stock_digest": user.low_stock_digest,
        "schedule": f"Every day at {settings.digest_hour_utc:02d}:00 UTC" if settings.digest_enabled else "Scheduled sending is turned off",
        "email_configured": mail.configured(),
        "email": user.email,
    }


@router.get("/preferences")
def get_preferences(user: User = Depends(current_user)):
    return _prefs(user)


@router.put("/preferences")
def set_preferences(body: PrefsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.low_stock_digest = body.low_stock_digest
    db.commit()
    return _prefs(user)


@router.post("/digest/test")
def send_test_digest(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Email today's digest to the signed-in user right now, so they can see exactly what it looks like."""
    digest = digest_mod.build_digest(db)
    if not digest:
        return {"sent": False, "items": 0, "reason": "Nothing needs attention right now, so there is nothing to send."}
    sent = digest_mod.send_digest([user], digest)
    if not sent:
        reason = "Email delivery isn't configured on this server." if not mail.configured() else "The email service didn't accept the message."
        return {"sent": False, "items": len(digest["items"]), "reason": reason}
    return {"sent": True, "items": len(digest["items"]), "reason": None}
