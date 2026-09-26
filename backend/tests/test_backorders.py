from helpers import act, detail, main_loc, make_op, ok, on_hand, party, product, receive, ship, uid


def validate(api, op, done: dict | None = None, backorder: bool = True, code: int | None = None):
    """Validate with per-line quantities, keyed by position in the document."""
    body = {"backorder": backorder}
    if done is not None:
        body["lines"] = [{"line_id": op["lines"][i]["id"], "done_qty": q} for i, q in done.items()]
    return ok(api.post(f"/operations/{op['id']}/validate", json=body), code)


def ready_receipt(api, p, qty, **kw):
    o = make_op(api, "IN", [(p, qty)], **kw)
    return act(api, o["id"], "todo")


def test_partial_receipt_creates_a_backorder(api):
    p = product(api)
    o = ready_receipt(api, p, 10, contact="Vendor A")
    done = validate(api, o, {0: 8})
    assert done["status"] == "done" and "Backorder" in done["message"]
    assert on_hand(api, p) == 8  # only what arrived
    assert done["lines"][0]["quantity"] == 8 and done["lines"][0]["ordered_qty"] == 10

    bo_ref = done["backorders"][0]
    bo = ok(api.get(f"/operations/{bo_ref['id']}"))
    assert bo["status"] == "ready" and bo["lines"][0]["quantity"] == 2
    assert bo["backorder_of"]["reference"] == o["reference"] and bo["contact"] == "Vendor A"
    assert bo["reference"] != o["reference"]

    validate(api, bo)  # the rest arrives later
    assert on_hand(api, p) == 10


def test_totals_follow_what_was_actually_received(api):
    p = product(api, unit_cost=100)
    o = ready_receipt(api, p, 10)
    assert o["subtotal"] == 1000
    done = validate(api, o, {0: 4})
    assert done["subtotal"] == 400 and done["tax_total"] == 72  # 18% of what really arrived


def test_no_backorder_cancels_the_remainder(api):
    p = product(api)
    o = ready_receipt(api, p, 10)
    done = validate(api, o, {0: 6}, backorder=False)
    assert "cancelled" in done["message"] and done["backorders"] == []
    assert on_hand(api, p) == 6


def test_a_full_validation_makes_no_backorder(api):
    p = product(api)
    done = validate(api, ready_receipt(api, p, 5))
    assert done["backorders"] == [] and done["message"] is None
    same = validate(api, ready_receipt(api, p, 5), {0: 5})  # explicit full quantity behaves the same
    assert same["backorders"] == []


def test_quantities_are_checked(api):
    p = product(api)
    o = ready_receipt(api, p, 10)
    assert "more than was ordered" in detail(api.post(f"/operations/{o['id']}/validate", json={"lines": [{"line_id": o["lines"][0]["id"], "done_qty": 11}]}), 409)
    assert "negative" in detail(api.post(f"/operations/{o['id']}/validate", json={"lines": [{"line_id": o["lines"][0]["id"], "done_qty": -1}]}), 409)
    assert "at least one" in detail(api.post(f"/operations/{o['id']}/validate", json={"lines": [{"line_id": o["lines"][0]["id"], "done_qty": 0}]}), 409)
    assert "does not belong" in detail(api.post(f"/operations/{o['id']}/validate", json={"lines": [{"line_id": 999999, "done_qty": 1}]}), 409)
    assert ok(api.get(f"/operations/{o['id']}"))["status"] == "ready"  # nothing changed


def test_multi_line_mix_of_full_partial_and_none(api):
    a, b, c = product(api), product(api), product(api)
    o = make_op(api, "IN", [(a, 10), (b, 10), (c, 10)])
    o = act(api, o["id"], "todo")
    done = validate(api, o, {0: 10, 1: 4, 2: 0})
    assert [l["quantity"] for l in done["lines"]] == [10, 4]  # the untouched line moved to the backorder
    assert (on_hand(api, a), on_hand(api, b), on_hand(api, c)) == (10, 4, 0)
    bo = ok(api.get(f"/operations/{done['backorders'][0]['id']}"))
    assert sorted(l["quantity"] for l in bo["lines"]) == [6, 10]


def test_partial_delivery_ships_what_was_packed_and_backorders_the_rest(api):
    p = product(api, stock=10)
    o = make_op(api, "OUT", [(p, 10)])
    act(api, o["id"], "todo")
    act(api, o["id"], "pick")
    o = act(api, o["id"], "pack")
    done = validate(api, o, {0: 6})
    assert done["status"] == "done" and on_hand(api, p) == 4
    bo = ok(api.get(f"/operations/{done['backorders'][0]['id']}"))
    assert bo["type"] == "OUT" and bo["status"] == "ready" and bo["lines"][0]["quantity"] == 4
    assert bo["picked"] is False  # the backorder is picked and packed on its own
    ship(api, bo["id"])
    assert on_hand(api, p) == 0


def test_partial_delivery_still_needs_pick_and_pack(api):
    p = product(api, stock=10)
    o = act(api, make_op(api, "OUT", [(p, 4)])["id"], "todo")
    assert "Pick and pack" in detail(api.post(f"/operations/{o['id']}/validate", json={"lines": [{"line_id": o["lines"][0]["id"], "done_qty": 2}]}), 409)


def test_backorder_of_a_delivery_waits_when_stock_is_short(api):
    p = product(api, stock=10)
    o = make_op(api, "OUT", [(p, 10)])
    act(api, o["id"], "todo")
    act(api, o["id"], "pick")
    o = act(api, o["id"], "pack")
    ok(api.post("/stock/adjust", json={"product_id": p["id"], "location_id": main_loc(api)["id"], "counted_qty": 7}))  # 3 units went missing
    stuck = act(api, o["id"], "validate")  # only 7 free but 10 needed
    assert stuck["status"] == "waiting"


def test_backorders_can_chain(api):
    p = product(api)
    first = validate(api, ready_receipt(api, p, 9), {0: 3})
    second = ok(api.get(f"/operations/{first['backorders'][0]['id']}"))
    second = validate(api, second, {0: 2})
    third = ok(api.get(f"/operations/{second['backorders'][0]['id']}"))
    assert third["lines"][0]["quantity"] == 4 and third["backorder_of"]["reference"] == second["reference"]
    assert on_hand(api, p) == 5


def test_only_ready_documents_can_be_validated_partially(api):
    p = product(api)
    draft = make_op(api, "IN", [(p, 5)])
    assert "Only ready" in detail(api.post(f"/operations/{draft['id']}/validate", json={"lines": [{"line_id": draft["lines"][0]["id"], "done_qty": 1}]}), 409)


def test_backorder_keeps_the_saved_contact(api):
    vendor = party(api, "vendor")
    p = product(api)
    o = ready_receipt(api, p, 10, party_id=vendor["id"])
    done = validate(api, o, {0: 5})
    bo = ok(api.get(f"/operations/{done['backorders'][0]['id']}"))
    assert bo["party"]["id"] == vendor["id"] and bo["contact"] == vendor["name"]
