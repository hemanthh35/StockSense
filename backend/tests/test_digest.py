from datetime import datetime

import pytest

from app.db import SessionLocal
from app.digest import build_digest, render, run_digest_if_due
from app.models import User
from conftest import PASSWORD, Api
from helpers import make_op, ok, product, uid


@pytest.fixture()
def outbox(monkeypatch):
    """Capture digest emails instead of sending them."""
    sent = []
    monkeypatch.setattr("app.digest.send_email", lambda to, subject, html: sent.append((to, subject, html)) or True)
    return sent


def new_user(anon, opted_in: bool):
    login = f"dg{uid(6).lower()}"
    r = ok(anon.post("/auth/signup", json={"login_id": login, "email": f"{login}@example.com", "password": PASSWORD, "confirm_password": PASSWORD}), 201)
    me = Api(anon.client, r["token"])
    if opted_in:
        ok(me.put("/notifications/preferences", json={"low_stock_digest": True}))
    return me, f"{login}@example.com"


def clear_claim(db):
    """Let a test pick its own fake 'today' without depending on earlier runs."""
    from app.models import Setting
    db.query(Setting).filter(Setting.key == "digest_last_date").delete()
    db.commit()


def test_preferences_default_to_off_and_can_be_toggled(anon):
    me, email = new_user(anon, opted_in=False)
    prefs = ok(me.get("/notifications/preferences"))
    assert prefs["low_stock_digest"] is False and prefs["email"] == email
    assert "03:00 UTC" in prefs["schedule"] or "turned off" in prefs["schedule"]
    assert ok(me.put("/notifications/preferences", json={"low_stock_digest": True}))["low_stock_digest"] is True
    assert ok(me.get("/notifications/preferences"))["low_stock_digest"] is True
    assert ok(me.put("/notifications/preferences", json={"low_stock_digest": False}))["low_stock_digest"] is False


def test_digest_lists_products_that_need_reordering(api):
    p = product(api, stock=2, reorder_min=20, reorder_qty=10)
    digest = build_digest(SessionLocal())
    item = next(i for i in digest["items"] if i["product_id"] == p["id"])
    assert item["suggested_qty"] == 20 and item["on_hand"] == 2  # shortfall 18 -> two multiples of 10


def test_digest_email_content_is_escaped(api):
    p = product(api, stock=1, reorder_min=5, name='<script>alert("x")</script> Widget')
    digest = build_digest(SessionLocal())
    subject, html = render(digest, "<b>bob</b>")
    assert "to reorder" in subject
    assert "<script>" not in html and "&lt;script&gt;" in html and "&lt;b&gt;bob" in html


def test_test_digest_goes_only_to_the_requesting_user(api, anon, outbox):
    product(api, stock=1, reorder_min=9)
    me, email = new_user(anon, opted_in=False)
    r = ok(me.post("/notifications/digest/test"))
    assert r["sent"] is True and r["items"] >= 1 and r["reason"] is None
    assert [to for to, _, _ in outbox] == [email]


def test_test_digest_explains_when_email_is_not_available(api, anon):
    product(api, stock=1, reorder_min=9)
    me, _ = new_user(anon, opted_in=False)
    r = ok(me.post("/notifications/digest/test"))  # no outbox patch: the (blank) Brevo config is used
    assert r["sent"] is False and "isn't configured" in r["reason"]


def test_scheduler_sends_once_a_day_to_opted_in_users_only(api, anon, outbox):
    product(api, stock=1, reorder_min=9)
    _, yes = new_user(anon, opted_in=True)
    _, no = new_user(anon, opted_in=False)
    with SessionLocal() as db:
        clear_claim(db)
        before_hour = datetime(2031, 5, 5, 2, 59)
        assert run_digest_if_due(db, before_hour, hour=3) == 0 and outbox == []  # too early, and it doesn't claim the day

        morning = datetime(2031, 5, 5, 3, 5)
        n = run_digest_if_due(db, morning, hour=3)
        assert n >= 1
        recipients = [to for to, _, _ in outbox]
        assert yes in recipients and no not in recipients

        count = len(outbox)
        assert run_digest_if_due(db, datetime(2031, 5, 5, 15, 0), hour=3) == 0  # same day: nothing more
        assert len(outbox) == count

        assert run_digest_if_due(db, datetime(2031, 5, 6, 3, 5), hour=3) >= 1  # next day: sends again
        assert len(outbox) > count


def test_scheduler_claims_the_day_even_when_nobody_is_subscribed(api, anon, outbox):
    with SessionLocal() as db:
        clear_claim(db)
        db.query(User).update({User.low_stock_digest: False})
        db.commit()
        assert run_digest_if_due(db, datetime(2032, 1, 1, 4, 0), hour=3) == 0
        assert run_digest_if_due(db, datetime(2032, 1, 1, 5, 0), hour=3) == 0
    assert outbox == []


def test_no_email_when_there_is_nothing_to_report(api, anon, outbox, monkeypatch):
    new_user(anon, opted_in=True)
    monkeypatch.setattr("app.digest.build_digest", lambda db: None)
    with SessionLocal() as db:
        clear_claim(db)
        assert run_digest_if_due(db, datetime(2033, 1, 1, 4, 0), hour=3) == 0
    assert outbox == []
