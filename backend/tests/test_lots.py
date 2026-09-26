from datetime import date, timedelta

from helpers import make_op, ok, product, main_loc


def iso(days):
    return (date.today() + timedelta(days=days)).isoformat()


def run(api, op, *steps):
    for s in steps:
        r = api.post(f"/operations/{op['id']}/{s}")
        assert r.status_code < 300, r.text
    return ok(api.get(f"/operations/{op['id']}"))


def receive(api, p, qty, lot=None, expiry=None):
    line = {"product_id": p["id"], "quantity": qty}
    if lot:
        line["lot_no"] = lot
    if expiry:
        line["expiry_date"] = expiry
    op = ok(api.post("/operations", json={"type": "IN", "lines": [line]}), 201)
    run(api, op, "todo", "validate")
    return op


def lots_of(api, p):
    rows = ok(api.get(f"/lots?q={p['sku']}"))["rows"]
    return {r["lot_no"]: r for r in rows}


def deliver(api, p, qty):
    op = make_op(api, "OUT", [(p, qty)])
    run(api, op, "todo", "pick", "pack", "validate")


def test_receipt_creates_lot_and_keeps_fields_on_the_line(api):
    p = product(api)
    op = ok(api.post("/operations", json={"type": "IN", "lines": [{"product_id": p["id"], "quantity": 10, "lot_no": "L-1", "expiry_date": iso(40)}]}), 201)
    assert op["lines"][0]["lot_no"] == "L-1" and op["lines"][0]["expiry_date"] == iso(40)
    assert lots_of(api, p) == {}  # nothing exists until the receipt is validated
    run(api, op, "todo", "validate")
    lot = lots_of(api, p)["L-1"]
    assert lot["remaining"] == 10 and lot["expiry_date"] == iso(40) and lot["level"] == "ok"


def test_expiry_without_lot_uses_the_receipt_reference_and_same_lot_merges(api):
    p = product(api)
    op = receive(api, p, 5, expiry=iso(10))
    assert list(lots_of(api, p)) == [ok(api.get(f"/operations/{op['id']}"))["reference"]]
    receive(api, p, 4, lot="A", expiry=iso(5))
    receive(api, p, 3, lot="A", expiry=iso(6))
    a = lots_of(api, p)["A"]
    assert a["remaining"] == 7 and a["received"] == 7 and a["expiry_date"] == iso(6)


def test_deliveries_use_the_earliest_expiry_first(api):
    p = product(api, stock=0)
    receive(api, p, 10, "LATE", iso(90))
    receive(api, p, 10, "SOON", iso(10))
    deliver(api, p, 12)
    got = lots_of(api, p)
    assert "SOON" not in got  # used up, so it no longer shows
    assert got["LATE"]["remaining"] == 8


def test_negative_count_uses_lots_and_untracked_stock_is_ignored(api):
    p = product(api, stock=5)  # 5 units that were never in a lot
    receive(api, p, 4, "X", iso(20))
    loc = main_loc(api)
    ok(api.post("/stock/adjust", json={"product_id": p["id"], "location_id": loc["id"], "counted_qty": 6}))  # 9 -> 6
    assert lots_of(api, p)["X"]["remaining"] == 1
    deliver(api, p, 6)  # more than the lot holds must not fail
    assert "X" not in lots_of(api, p)


def test_expiry_levels_filter_and_summary(api):
    p = product(api)
    receive(api, p, 1, "EXP", iso(-3))
    receive(api, p, 1, "SOON", iso(7))
    receive(api, p, 1, "FAR", iso(200))
    receive(api, p, 1, "NONE")
    lots = lots_of(api, p)
    assert list(lots) == ["EXP", "SOON", "FAR", "NONE"]  # earliest expiry first, no expiry last
    body = ok(api.get(f"/lots?q={p['sku']}&status=expired"))
    assert [r["lot_no"] for r in body["rows"]] == ["EXP"] and body["rows"][0]["level"] == "expired"
    assert [r["lot_no"] for r in ok(api.get(f"/lots?q={p['sku']}&status=soon&days=10"))["rows"]] == ["SOON"]
    s = ok(api.get("/lots"))["summary"]
    assert s["expired"] >= 1 and s["expiring_soon"] >= 1
    k = ok(api.get("/dashboard"))["kpis"]
    assert k["expired_lots"] == s["expired"] and k["expiring_lots"] == s["expiring_soon"]


def test_partial_receipt_and_backorder_keep_the_lot(api):
    p = product(api)
    op = ok(api.post("/operations", json={"type": "IN", "lines": [{"product_id": p["id"], "quantity": 10, "lot_no": "P1", "expiry_date": iso(30)}]}), 201)
    ok(api.post(f"/operations/{op['id']}/todo"))
    full = ok(api.get(f"/operations/{op['id']}"))
    ok(api.post(f"/operations/{op['id']}/validate", json={"lines": [{"line_id": full["lines"][0]["id"], "done_qty": 4}], "backorder": True}))
    assert lots_of(api, p)["P1"]["remaining"] == 4
    bo = ok(api.get(f"/operations?q={p['sku']}"))
    back = next(o for o in bo if o["status"] != "done")
    detail = ok(api.get(f"/operations/{back['id']}"))
    assert detail["lines"][0]["lot_no"] == "P1" and detail["lines"][0]["expiry_date"] == iso(30)
    run(api, back, "validate")
    assert lots_of(api, p)["P1"]["remaining"] == 10


def test_lot_fields_are_ignored_on_deliveries(api):
    p = product(api, stock=3)
    op = ok(api.post("/operations", json={"type": "OUT", "lines": [{"product_id": p["id"], "quantity": 1, "lot_no": "Z", "expiry_date": iso(5)}]}), 201)
    assert op["lines"][0]["lot_no"] is None
