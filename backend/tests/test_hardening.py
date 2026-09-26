import threading

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import ratelimit, stock
from app.config import Settings
from app.config import settings as live_settings
from app.db import SessionLocal, engine
from app.migrations import run_migrations
from app.models import Operation, StockQuant
from conftest import PASSWORD, Api
from helpers import act, detail, main_loc, make_op, ok, on_hand, party, product, ship, uid

CONFLICT = "changed by someone else"


# ---------------------------------------------------------------- optimistic locking
def test_a_stale_product_edit_is_refused(api):
    p = product(api, unit_cost=100)
    body = lambda price, v: {"name": p["name"], "sku": p["sku"], "unit_cost": price, "version": v}
    first = ok(api.put(f"/products/{p['id']}", json=body(110, p["version"])))
    assert first["version"] == p["version"] + 1 and first["unit_cost"] == 110
    assert CONFLICT in detail(api.put(f"/products/{p['id']}", json=body(120, p["version"])), 409)  # someone else got there first
    assert ok(api.get(f"/products?q={p['sku']}"))[0]["unit_cost"] == 110  # and their change survived
    ok(api.put(f"/products/{p['id']}", json=body(130, first["version"])))  # reloading fixes it
    ok(api.put(f"/products/{p['id']}", json={"name": p["name"], "sku": p["sku"], "unit_cost": 140}))  # no version: scripts still work


def test_a_stale_contact_edit_is_refused(api):
    c = party(api)
    ok(api.put(f"/parties/{c['id']}", json={"name": c["name"], "kind": "both", "phone": "111", "version": c["version"]}))
    assert CONFLICT in detail(api.put(f"/parties/{c['id']}", json={"name": c["name"], "kind": "both", "phone": "222", "version": c["version"]}), 409)


def test_a_stale_document_edit_or_action_is_refused(api):
    p = product(api, stock=10)
    o = make_op(api, "OUT", [(p, 2)])
    line = [{"product_id": p["id"], "quantity": 2}]
    saved = ok(api.put(f"/operations/{o['id']}", json={"type": "OUT", "contact": "First", "lines": line, "version": o["version"]}))
    assert saved["version"] > o["version"]
    assert CONFLICT in detail(api.put(f"/operations/{o['id']}", json={"type": "OUT", "contact": "Second", "lines": line, "version": o["version"]}), 409)
    assert ok(api.get(f"/operations/{o['id']}"))["contact"] == "First"
    assert CONFLICT in detail(api.post(f"/operations/{o['id']}/todo?version={o['version']}"), 409)
    ready = ok(api.post(f"/operations/{o['id']}/todo?version={saved['version']}"))
    assert ready["status"] == "ready" and ready["version"] > saved["version"]
    assert CONFLICT in detail(api.post(f"/operations/{o['id']}/pick?version={saved['version']}"), 409)


def test_every_workflow_step_moves_the_version(api):
    p = product(api, stock=5)
    o = make_op(api, "OUT", [(p, 1)])
    seen = [o["version"]]
    for a in ("todo", "pick", "pack", "validate"):
        seen.append(act(api, o["id"], a)["version"])
    assert seen == sorted(set(seen)) and len(seen) == 5


def test_stock_arriving_moves_the_version_of_orders_it_unblocks(api):
    p = product(api, stock=1)
    o = make_op(api, "OUT", [(p, 5)])
    waiting = act(api, o["id"], "todo")
    assert waiting["status"] == "waiting"
    r = make_op(api, "IN", [(p, 10)])
    act(api, r["id"], "todo")
    act(api, r["id"], "validate")
    after = ok(api.get(f"/operations/{o['id']}"))
    assert after["status"] == "ready" and after["version"] > waiting["version"]
    assert CONFLICT in detail(api.post(f"/operations/{o['id']}/check?version={waiting['version']}"), 409)  # the screen was out of date


# ---------------------------------------------------------------- stock can never go negative
def test_the_database_itself_refuses_negative_stock(api):
    p = product(api, stock=3)
    with SessionLocal() as db:
        q = db.query(StockQuant).filter(StockQuant.product_id == p["id"]).one()
        q.quantity = -1
        with pytest.raises(IntegrityError):
            db.commit()


def test_two_people_validating_at_once_cannot_oversell(api):
    """Two ready deliveries for the same last units are validated in parallel. Exactly one wins; stock never dips below zero."""
    for _round in range(4):
        p = product(api, stock=10)
        a, b = make_op(api, "OUT", [(p, 8)]), make_op(api, "OUT", [(p, 8)])
        act(api, a["id"], "todo")
        with SessionLocal() as db:  # simulate the reservation race: both ended up Ready although only one can be served
            for oid in (a["id"], b["id"]):
                op = db.get(Operation, oid)
                op.status, op.picked_at, op.packed_at = "ready", stock.utcnow(), stock.utcnow()
            db.commit()

        gate, outcomes = threading.Barrier(2), {}

        def worker(oid):
            with SessionLocal() as db:
                op = db.get(Operation, oid)
                gate.wait()
                try:
                    stock.action_validate(db, op)
                    db.commit()
                    outcomes[oid] = op.status
                except IntegrityError:
                    db.rollback()
                    outcomes[oid] = "refused"

        threads = [threading.Thread(target=worker, args=(oid,)) for oid in (a["id"], b["id"])]
        [t.start() for t in threads]
        [t.join() for t in threads]

        # the row lock makes the loser wait, re-check, and move to Waiting: no crash, no oversell
        assert sorted(outcomes.values()) == ["done", "waiting"], outcomes
        assert on_hand(api, p) == 2  # 10 - 8, and never -6
        loser = next(oid for oid, st in outcomes.items() if st != "done")
        assert ok(api.get(f"/operations/{loser}"))["status"] == "waiting"


def test_the_race_loser_gets_a_clear_message_through_the_api(api, monkeypatch):
    p = product(api, stock=4)
    o = make_op(api, "OUT", [(p, 3)])
    act(api, o["id"], "todo")
    act(api, o["id"], "pick")
    act(api, o["id"], "pack")
    monkeypatch.setattr(stock, "line_shortages", lambda *a, **k: {})  # pretend the stale check passed
    with SessionLocal() as db:  # meanwhile someone else took the stock
        q = db.query(StockQuant).filter(StockQuant.product_id == p["id"]).one()
        q.quantity = 1
        db.commit()
    assert "Not enough stock" in detail(api.post(f"/operations/{o['id']}/validate"), 409)
    assert ok(api.get(f"/operations/{o['id']}"))["status"] == "ready"  # nothing half-done was saved


# ---------------------------------------------------------------- exact money
def test_money_is_exact_and_rounds_half_up(api):
    p = product(api, unit_cost=0.1)
    o = make_op(api, "OUT", [(p, 3)])
    assert o["subtotal"] == 0.3  # not 0.30000000000000004
    half = ok(api.post("/operations", json={"type": "IN", "lines": [{"product_id": p["id"], "quantity": 1, "unit_price": 0.125}]}), 201)
    assert half["subtotal"] == 0.13  # 0.125 rounds up to 0.13; binary floats would give 0.12


def test_long_columns_of_small_amounts_add_up(api):
    p = product(api, unit_cost=0.1)
    lines = [{"product_id": p["id"], "quantity": 1} for _ in range(100)]
    o = ok(api.post("/operations", json={"type": "OUT", "lines": lines}), 201)
    assert (o["subtotal"], o["tax_total"], o["total"]) == (10.0, 2.0, 12.0)  # each line: 0.10 + 0.02


def test_prices_keep_four_decimals_and_quantities_three(api):
    p = product(api, unit_cost=0.0125, reorder_min=0.001)
    got = ok(api.get(f"/products?q={p['sku']}"))[0]
    assert got["unit_cost"] == 0.0125 and got["reorder_min"] == 0.001
    o = ok(api.post("/operations", json={"type": "IN", "lines": [{"product_id": p["id"], "quantity": 0.001, "unit_price": 1000}]}), 201)
    assert o["lines"][0]["quantity"] == 0.001 and o["subtotal"] == 1.0


def test_valuation_sums_exactly_in_the_database(api):
    p = product(api, unit_cost=0.1, cost_price=0.1, stock=3)
    assert ok(api.get(f"/reports/valuation?q={p['sku']}"))["totals"]["value"] == 0.3


# ---------------------------------------------------------------- input limits
def test_absurd_input_is_rejected_before_it_reaches_the_database(api):
    sku = f"L{uid()}"
    assert api.post("/products", json={"name": "x" * 151, "sku": sku}).status_code == 422
    assert api.post("/products", json={"name": "x", "sku": "s" * 51}).status_code == 422
    assert api.post("/products", json={"name": "x", "sku": sku, "unit_cost": -1}).status_code == 422
    assert api.post("/products", json={"name": "x", "sku": sku, "unit_cost": 1e12}).status_code == 422
    assert api.post("/products", json={"name": "x", "sku": sku, "reorder_min": -5}).status_code == 422
    assert api.post("/products", json={"name": "x", "sku": sku, "initial_stock": 1e12}).status_code == 422
    assert api.post("/parties", json={"name": "n" * 151}).status_code == 422
    assert api.post("/parties", json={"name": "n", "address": "a" * 301}).status_code == 422
    assert api.post("/categories", json={"name": "c" * 101}).status_code == 422
    assert api.post("/taxes", json={"name": "t" * 61, "rate": 1}).status_code == 422
    assert api.post("/warehouses", json={"name": "w" * 101, "short_code": "W1"}).status_code == 422
    p = product(api)
    assert api.post("/operations", json={"type": "IN", "lines": [{"product_id": p["id"], "quantity": 1e12}]}).status_code == 422
    assert api.post("/operations", json={"type": "IN", "lines": [{"product_id": p["id"], "quantity": 1, "unit_price": -3}]}).status_code == 422
    assert api.post("/operations", json={"type": "IN", "contact": "c" * 151, "lines": []}).status_code == 422
    too_many = [{"product_id": p["id"], "quantity": 1}] * 501
    assert api.post("/operations", json={"type": "IN", "lines": too_many}).status_code == 422
    assert api.post("/stock/adjust", json={"product_id": p["id"], "location_id": main_loc(api)["id"], "counted_qty": -1}).status_code == 422


def test_password_and_login_limits(anon):
    long_pw = "Aa!" + "b" * 80
    assert "72 characters" in detail(anon.post("/auth/signup", json={"login_id": f"lim{uid(6).lower()}", "email": f"{uid()}@example.com", "password": long_pw, "confirm_password": long_pw}), 422)
    assert anon.post("/auth/login", json={"login_id": "x" * 70, "password": "y"}).status_code == 422


# ---------------------------------------------------------------- rate limiting
@pytest.fixture()
def limits_on(monkeypatch):
    monkeypatch.setattr(live_settings, "rate_limit_enabled", True)
    ratelimit.reset()
    yield
    ratelimit.reset()


def test_login_attempts_are_limited_per_person(limits_on, anon):
    body = {"login_id": f"brute{uid(4).lower()}", "password": "wrong"}
    for _ in range(10):
        assert anon.post("/auth/login", json=body).status_code == 401
    r = anon.post("/auth/login", json=body)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0 and "Too many attempts" in r.json()["detail"]
    # a different login id from the same address is not caught by that person's counter
    assert anon.post("/auth/login", json={"login_id": "someoneelse", "password": "x"}).status_code == 401


def test_one_inbox_cannot_be_flooded_with_codes(limits_on, anon, sent_otps):
    from conftest import PASSWORD
    login = f"flood{uid(4).lower()}"
    email = f"{login}@example.com"
    ok(anon.post("/auth/signup", json={"login_id": login, "email": email, "password": PASSWORD, "confirm_password": PASSWORD}), 201)
    for _ in range(3):
        assert anon.post("/auth/forgot-password", json={"email": email}).status_code == 200
    assert anon.post("/auth/forgot-password", json={"email": email}).status_code == 429
    assert len(sent_otps) == 3  # the fourth never reached the mail service
    assert anon.post("/auth/forgot-password", json={"email": f"other{uid(4).lower()}@example.com"}).status_code == 200


def test_signups_are_limited_per_address(limits_on, anon):
    for i in range(10):
        login = f"mass{i}{uid(4).lower()}"
        assert anon.post("/auth/signup", json={"login_id": login, "email": f"{login}@example.com", "password": PASSWORD, "confirm_password": PASSWORD}).status_code == 201
    assert anon.post("/auth/signup", json={"login_id": "toomany1", "email": "toomany1@example.com", "password": PASSWORD, "confirm_password": PASSWORD}).status_code == 429


def test_the_limiter_can_be_switched_off(anon):
    body = {"login_id": f"free{uid(4).lower()}", "password": "wrong"}
    assert all(anon.post("/auth/login", json=body).status_code == 401 for _ in range(15))


def test_otp_reset_attempts_are_limited(limits_on, anon):
    body = {"email": f"nobody{uid(4).lower()}@example.com", "otp": "000000", "new_password": "New!Passw0rd", "confirm_password": "New!Passw0rd"}
    codes = [anon.post("/auth/reset-password", json=body).status_code for _ in range(11)]
    assert codes[:10] == [400] * 10 and codes[10] == 429


# ---------------------------------------------------------------- secure defaults
def test_insecure_secrets_are_detected():
    assert Settings(secret_key="dev-secret").check_secure()
    assert Settings(secret_key="").check_secure()
    assert Settings(secret_key="change-me-to-a-long-random-string").check_secure()
    assert Settings(secret_key="short").check_secure()
    assert Settings(secret_key="k" * 40).check_secure() is None


def test_production_refuses_to_start_with_a_weak_secret(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app, app_settings

    monkeypatch.setattr(app_settings, "app_env", "production")
    monkeypatch.setattr(app_settings, "secret_key", "dev-secret")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        with TestClient(app):
            pass


def test_cors_origins_come_from_the_environment():
    s = Settings(cors_origins="https://a.example, https://b.example ,")
    assert s.cors_list == ["https://a.example", "https://b.example"]
    assert Settings(app_env="production").production and not Settings().production


def test_health_checks_the_database(anon):
    r = anon.get("/health")
    assert r.status_code == 200 and r.json() == {"ok": True, "database": "up"}


# ---------------------------------------------------------------- migrations
def test_migrations_are_repeatable_and_upgrade_old_columns():
    run_migrations(engine)
    run_migrations(engine)  # idempotent

    with engine.begin() as conn:  # pretend this column still has the old floating-point type
        conn.execute(text("ALTER TABLE stock_quants ALTER COLUMN quantity TYPE double precision"))
    run_migrations(engine)
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT data_type, numeric_precision, numeric_scale FROM information_schema.columns "
            "WHERE table_name='stock_quants' AND column_name='quantity'")).one()
        assert tuple(row) == ("numeric", 14, 3)
        assert conn.execute(text("SELECT 1 FROM pg_constraint WHERE conname='ck_stock_quants_nonnegative'")).first()
        idx = {r[0] for r in conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename='operation_lines'"))}
        assert {"ix_operation_lines_operation_id", "ix_operation_lines_product_id"} <= idx


def test_stock_still_adds_up_after_the_upgrade(api):
    p = product(api, stock=7)
    run_migrations(engine)
    assert on_hand(api, p) == 7
