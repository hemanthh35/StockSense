from helpers import act, detail, main_loc, make_op, ok, on_hand, product, receive, ship, stock_locations


def test_receipt_increases_stock(api):
    p = product(api)
    assert on_hand(api, p) == 0
    o = make_op(api, "IN", [(p, 20)], contact="Vendor A")
    assert o["status"] == "draft" and o["reference"].startswith("WH/IN/")
    assert act(api, o["id"], "todo")["status"] == "ready"
    assert on_hand(api, p) == 0  # nothing moves until validated
    assert act(api, o["id"], "validate")["status"] == "done"
    assert on_hand(api, p) == 20


def test_references_increment(api):
    p = product(api)
    a, b = make_op(api, "IN", [(p, 1)]), make_op(api, "IN", [(p, 1)])
    na, nb = int(a["reference"].split("/")[-1]), int(b["reference"].split("/")[-1])
    assert nb == na + 1


def test_delivery_short_on_stock_waits_then_recovers(api):
    p = product(api, stock=5)
    out = make_op(api, "OUT", [(p, 8)], contact="Azure Interior")
    body = act(api, out["id"], "todo")
    assert body["status"] == "waiting" and "not in stock" in body["message"]
    assert body["lines"][0]["short"] is True and body["lines"][0]["missing"] == 3

    receive(api, p, 10)  # stock arrives -> waiting order is promoted on its own
    assert ok(api.get(f"/operations/{out['id']}"))["status"] == "ready"

    assert ship(api, out["id"])["status"] == "done"
    assert on_hand(api, p) == 5 + 10 - 8


def test_ready_orders_reserve_stock(api):
    p = product(api, stock=10)
    a = make_op(api, "OUT", [(p, 8)])
    b = make_op(api, "OUT", [(p, 8)])
    assert act(api, a["id"], "todo")["status"] == "ready"
    assert act(api, b["id"], "todo")["status"] == "waiting"  # only 2 free while A holds 8
    act(api, a["id"], "cancel")  # releases the reservation
    assert act(api, b["id"], "check")["status"] == "ready"


def test_delivery_needs_pick_and_pack(api):
    p = product(api, stock=10)
    o = make_op(api, "OUT", [(p, 3)])
    act(api, o["id"], "todo")
    assert "Pick and pack" in detail(api.post(f"/operations/{o['id']}/validate"), 409)
    assert "Pick the items" in detail(api.post(f"/operations/{o['id']}/pack"), 409)
    assert act(api, o["id"], "pick")["picked"] is True
    assert "already picked" in detail(api.post(f"/operations/{o['id']}/pick"), 409)
    assert "Pick and pack" in detail(api.post(f"/operations/{o['id']}/validate"), 409)  # picked but not packed
    assert act(api, o["id"], "pack")["packed"] is True
    assert act(api, o["id"], "validate")["status"] == "done"
    assert on_hand(api, p) == 7


def test_pick_pack_is_for_deliveries_only(api):
    p = product(api)
    o = make_op(api, "IN", [(p, 2)])
    act(api, o["id"], "todo")
    assert "deliveries" in detail(api.post(f"/operations/{o['id']}/pick"), 409)


def test_pick_requires_ready(api):
    p = product(api, stock=5)
    o = make_op(api, "OUT", [(p, 1)])
    assert "Ready" in detail(api.post(f"/operations/{o['id']}/pick"), 409)  # still a draft


def test_editing_resets_picking(api):
    p = product(api, stock=10)
    o = make_op(api, "OUT", [(p, 2)])
    act(api, o["id"], "todo")
    act(api, o["id"], "pick")
    edited = ok(api.put(f"/operations/{o['id']}", json={"type": "OUT", "lines": [{"product_id": p["id"], "quantity": 3}]}))
    assert edited["status"] == "draft" and edited["picked"] is False and edited["packed"] is False


def test_internal_transfer_moves_stock_between_locations(api):
    s1, s2 = stock_locations(api)[:2]
    p = product(api, stock=10, loc=s1)
    o = make_op(api, "INT", [(p, 4)], source_location_id=s1["id"], dest_location_id=s2["id"])
    act(api, o["id"], "todo")
    act(api, o["id"], "validate")
    by_loc = {l["location"]: l["on_hand"] for l in ok(api.get(f"/stock?q={p['sku']}"))[0]["locations"]}
    assert by_loc[s1["full_name"]] == 6 and by_loc[s2["full_name"]] == 4
    assert on_hand(api, p) == 10  # total unchanged


def test_transfer_can_short_too(api):
    s1, s2 = stock_locations(api)[:2]
    p = product(api, stock=2, loc=s1)
    o = make_op(api, "INT", [(p, 5)], source_location_id=s1["id"], dest_location_id=s2["id"])
    assert act(api, o["id"], "todo")["status"] == "waiting"


def test_adjustment_sets_count_and_logs_move(api):
    p = product(api, stock=10)
    loc = main_loc(api)
    r = ok(api.post("/stock/adjust", json={"product_id": p["id"], "location_id": loc["id"], "counted_qty": 7}))
    assert r["difference"] == -3 and on_hand(api, p) == 7
    rows = ok(api.get(f"/moves?q={p['sku']}"))
    adj = [m for m in rows if m["type"] == "ADJ" and m["quantity"] == 3]
    assert adj and adj[0]["direction"] == "out"  # a loss shows as an outgoing move


def test_cancel_and_finished_documents_are_locked(api):
    p = product(api, stock=5)
    o = make_op(api, "OUT", [(p, 1)])
    act(api, o["id"], "cancel")
    assert "no longer" in detail(api.post(f"/operations/{o['id']}/cancel"), 409)
    done = receive(api, p, 1)
    assert "cannot be edited" in detail(api.put(f"/operations/{done['id']}", json={"type": "IN", "lines": []}), 409)


def test_validation_errors(api):
    p = product(api)
    assert "greater than zero" in detail(api.post("/operations", json={"type": "IN", "lines": [{"product_id": p["id"], "quantity": 0}]}), 422)
    assert "Unknown product" in detail(api.post("/operations", json={"type": "IN", "lines": [{"product_id": 999999, "quantity": 1}]}), 422)
    assert "IN, OUT or INT" in detail(api.post("/operations", json={"type": "ADJ", "lines": []}), 422)
    empty = make_op(api, "IN", [])
    assert "at least one product" in detail(api.post(f"/operations/{empty['id']}/todo"), 409)


def test_duplicate_copies_lines_as_draft(api):
    p = product(api, stock=5)
    o = make_op(api, "OUT", [(p, 2)], contact="Deco Addict")
    act(api, o["id"], "todo")
    copy = ok(api.post(f"/operations/{o['id']}/duplicate"))
    assert copy["status"] == "draft" and copy["id"] != o["id"] and copy["contact"] == "Deco Addict"
    assert copy["lines"][0]["quantity"] == 2
    assert "duplicated" in detail(api.post(f"/operations/{ok(api.get('/operations?type=ADJ'))[0]['id']}/duplicate"), 409)


def test_contacts_are_remembered(api):
    p = product(api)
    make_op(api, "IN", [(p, 1)], contact="Remember Me Ltd")
    assert "Remember Me Ltd" in ok(api.get("/contacts"))
