"""Daily low-stock digest: what to reorder, what's late, what's stuck waiting. Sent through Brevo."""
import logging
from datetime import date, datetime
from html import escape

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .mail import send_email
from .models import Operation, Setting, User
from .routers.inventory import _suggestions

log = logging.getLogger("stocksense.digest")
LAST_SENT_KEY = "digest_last_date"


def build_digest(db: Session) -> dict | None:
    """None means there is nothing worth emailing."""
    items = _suggestions(db, None)
    today = date.today()
    open_states = ("draft", "waiting", "ready")
    late = db.scalar(
        select(func.count()).select_from(Operation).where(
            Operation.type.in_(["IN", "OUT"]), Operation.status.in_(open_states), Operation.schedule_date < today
        )
    ) or 0
    waiting = db.scalar(
        select(func.count()).select_from(Operation).where(Operation.type == "OUT", Operation.status == "waiting")
    ) or 0
    if not items and not late and not waiting:
        return None
    return {"items": items, "late": late, "waiting": waiting}


def _num(n: float) -> str:
    return f"{n:g}"


def render(digest: dict, login_id: str) -> tuple[str, str]:
    items = digest["items"]
    subject = (
        f"StockSense: {len(items)} product{'s' if len(items) != 1 else ''} to reorder"
        if items else "StockSense: daily summary"
    )
    rows = "".join(
        f"<tr><td style='padding:8px 12px;border-bottom:1px solid #eee'>{escape(i['name'])}"
        f"<br><span style='color:#888;font-size:12px'>{escape(i['sku'])}</span></td>"
        f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:right'>{_num(i['on_hand'])}</td>"
        f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:right'>{_num(i['incoming'])}</td>"
        f"<td style='padding:8px 12px;border-bottom:1px solid #eee;text-align:right'><b>{_num(i['suggested_qty'])}</b></td></tr>"
        for i in items[:25]
    )
    more = f"<p style='color:#888'>…and {len(items) - 25} more.</p>" if len(items) > 25 else ""
    table = (
        "<table style='border-collapse:collapse;width:100%;font-size:14px'>"
        "<tr style='background:#f6f4fb;text-align:left'><th style='padding:8px 12px'>Product</th>"
        "<th style='padding:8px 12px;text-align:right'>On hand</th>"
        "<th style='padding:8px 12px;text-align:right'>Incoming</th>"
        "<th style='padding:8px 12px;text-align:right'>Suggested order</th></tr>"
        f"{rows}</table>{more}"
        if items else "<p>Nothing needs reordering.</p>"
    )
    extras = []
    if digest["late"]:
        extras.append(f"<li><b>{digest['late']}</b> receipt/delivery document{'s are' if digest['late'] != 1 else ' is'} late</li>")
    if digest["waiting"]:
        extras.append(f"<li><b>{digest['waiting']}</b> deliver{'ies are' if digest['waiting'] != 1 else 'y is'} waiting for stock</li>")
    body = (
        "<div style='font-family:system-ui,Segoe UI,sans-serif;max-width:640px;margin:auto;color:#1d1a2b'>"
        f"<h2 style='margin-bottom:4px'>Good morning, {escape(login_id)}</h2>"
        "<p style='color:#5f5a77;margin-top:0'>Here is what needs attention in StockSense today.</p>"
        f"{table}"
        f"{'<ul>' + ''.join(extras) + '</ul>' if extras else ''}"
        "<p style='color:#888;font-size:12px;margin-top:24px'>You receive this because the daily digest is on in "
        "My profile. Turn it off there at any time.</p></div>"
    )
    return subject, body


def send_digest(users: list[User], digest: dict) -> int:
    """One email per person (nobody sees anyone else's address). Returns how many Brevo accepted."""
    sent = 0
    for u in users:
        subject, html = render(digest, u.login_id)
        if send_email(u.email, subject, html):
            sent += 1
    return sent


def run_digest_if_due(db: Session, now: datetime, hour: int) -> int:
    """Send at most once per day, after `hour` UTC. The day is claimed *before* sending so a restart
    or a second worker can't send it twice. Returns the number of emails sent."""
    if now.hour < hour:
        return 0
    today = now.date().isoformat()
    row = db.execute(select(Setting).where(Setting.key == LAST_SENT_KEY).with_for_update()).scalar_one_or_none()
    if row and row.value == today:
        return 0
    try:
        if row:
            row.value = today
        else:
            db.add(Setting(key=LAST_SENT_KEY, value=today))
        db.commit()
    except IntegrityError:  # another worker claimed it first
        db.rollback()
        return 0

    users = list(db.scalars(select(User).where(User.low_stock_digest.is_(True))))
    if not users:
        return 0
    digest = build_digest(db)
    if not digest:
        return 0
    sent = send_digest(users, digest)
    log.info("Low-stock digest: %s of %s emails accepted", sent, len(users))
    return sent
