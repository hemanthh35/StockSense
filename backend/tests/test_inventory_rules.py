from helpers import act, detail, main_loc, make_op, ok, on_hand, product, receive, stock_locations, uid, warehouse


# ---------------------------------------------------------------- multi-warehouse
def test_reference_follows_the_chosen_warehouse(api):
    wh, loc = warehouse(api)
    p = product(api)
    o = make_op(api, "IN", [(p, 5)], warehouse_id=wh["id"])
    assert o["reference"].startswith(f"{wh['short_code']}/IN/") and o["dest_location"]["id"] == loc["id"]
    assert o["warehouse"]["id"] == wh["id"]


def test_location_must_belong_to_the_warehouse(api):
    wh, loc = warehouse(api)
    other = main_loc(api)
    p = product(api)
    body = {"type": "IN", "warehouse_id": wh["id"], "dest_location_id": other["id"], "lines": [{"product_id": p["id"], "quantity": 1}]}
    assert "different warehouse" in detail(api.post("/operations", json=body), 422)


def test_warehouse_is_inferred_from_the_location(api):
    wh, loc = warehouse(api)
    p = product(api)
    o = make_op(api, "OUT", [(p, 1)], source_location_id=loc["id"])
    assert o["warehouse"]["id"] == wh["id"] and o["reference"].startswith(wh["short_code"])


def test_transfer_can_cross_warehouses(api):
    wh, loc = warehouse(api)
    src = main_loc(api)
    p = product(api, stock=10, loc=src)
    o = make_op(api, "INT", [(p, 4)], source_location_id=src["id"], dest_location_id=loc["id"])
    assert o["reference"].startswith("WH/INT/")  # numbered from the From location's warehouse
    act(api, o["id"], "todo")
    act(api, o["id"], "validate")
    by_loc = {l["location"]: l["on_hand"] for l in ok(api.get(f"/stock?q={p['sku']}"))[0]["locations"]}
    assert by_loc[loc["full_name"]] == 4 and by_loc[src["full_name"]] == 6
    # the transfer shows up under both warehouses
    for w in (1, wh["id"]):
        assert o["id"] in [x["id"] for x in ok(api.get(f"/operations?type=INT&warehouse_id={w}"))]


def test_transfer_rules(api):
    src = main_loc(api)
    p = product(api)
    assert "different" in detail(api.post("/operations", json={"type": "INT", "source_location_id": src["id"], "dest_location_id": src["id"], "lines": []}), 422)
    assert "From and To" in detail(api.post("/operations", json={"type": "INT", "lines": []}), 422)
    vendor = next(l for l in ok(api.get("/locations")) if l["type"] == "vendor")
    assert "stock locations" in detail(api.post("/operations", json={"type": "INT", "source_location_id": vendor["id"], "dest_location_id": src["id"], "lines": []}), 422)


def test_warehouse_short_code_is_unique(api):
    wh, _ = warehouse(api, with_location=False)
    assert "already used" in detail(api.post("/warehouses", json={"name": "Copy", "short_code": wh["short_code"].lower()}), 409)


# ---------------------------------------------------------------- reordering
def test_reorder_suggestion_uses_multiples_and_incoming(api):
    p = product(api, stock=42, reorder_min=100, reorder_qty=40)
    sug = {s["product_id"]: s for s in ok(api.get("/reorder/suggestions"))}
    assert sug[p["id"]]["suggested_qty"] == 80  # shortfall 58 -> two multiples of 40

    r = ok(api.post("/reorder/receipt", json={"product_ids": [p["id"]]}), 201)
    assert r["status"] == "draft" and r["type"] == "IN" and r["lines"][0]["quantity"] == 80
    sug = {s["product_id"]: s for s in ok(api.get("/reorder/suggestions"))}
    assert p["id"] not in sug  # the open receipt covers it, so no double ordering
    assert "Nothing needs reordering" in detail(api.post("/reorder/receipt", json={"product_ids": [p["id"]]}), 422)


def test_products_without_a_rule_are_not_suggested(api):
    p = product(api, stock=0)  # no reorder level, no reorder quantity
    assert p["id"] not in [s["product_id"] for s in ok(api.get("/reorder/suggestions"))]


def test_reorder_without_quantity_orders_the_shortfall(api):
    p = product(api, stock=3, reorder_min=10)
    s = next(x for x in ok(api.get("/reorder/suggestions")) if x["product_id"] == p["id"])
    assert s["suggested_qty"] == 7


def test_reorder_receipt_for_unknown_products_is_refused(api):
    assert detail(api.post("/reorder/receipt", json={"product_ids": [999999]}), 422)


def test_dashboard_reports_reorder_count(api):
    before = ok(api.get("/dashboard"))["reorder_count"]
    p = product(api, stock=1, reorder_min=50, reorder_qty=25)
    d = ok(api.get("/dashboard"))
    assert d["reorder_count"] == before + 1
    ok(api.post("/reorder/receipt", json={"product_ids": [p["id"]]}), 201)
    assert ok(api.get("/dashboard"))["reorder_count"] == before  # covered by the draft receipt


# ---------------------------------------------------------------- categories
def test_category_lifecycle(api):
    name = f"Cat {uid()}"
    c = ok(api.post("/categories", json={"name": name}), 201)
    assert ok(api.put(f"/categories/{c['id']}", json={"name": name + " v2"}))["name"] == name + " v2"

    other = ok(api.post("/categories", json={"name": f"Cat {uid()}"}), 201)
    assert "already exists" in detail(api.put(f"/categories/{c['id']}", json={"name": other["name"].upper()}), 409)

    p = product(api, category_id=c["id"])
    assert "still use" in detail(api.delete(f"/categories/{c['id']}"), 409)
    cats = {x["id"]: x for x in ok(api.get("/categories"))}
    assert cats[c["id"]]["products"] == 1

    ok(api.put(f"/products/{p['id']}", json={"name": p["name"], "sku": p["sku"], "category_id": other["id"]}))
    assert ok(api.delete(f"/categories/{c['id']}"))["ok"] is True
    assert c["id"] not in [x["id"] for x in ok(api.get("/categories"))]


def test_creating_an_existing_category_returns_it(api):
    name = f"Same {uid()}"
    a = ok(api.post("/categories", json={"name": name}), 201)
    b = ok(api.post("/categories", json={"name": name.upper()}), 201)
    assert a["id"] == b["id"]


# ---------------------------------------------------------------- search
def test_search_finds_documents_by_product_name_and_sku(api):
    p, q = product(api), product(api)
    o = make_op(api, "IN", [(p, 1), (q, 1)], contact="Searchy Co")
    ids = lambda term: [x["id"] for x in ok(api.get(f"/operations?q={term}"))]
    assert o["id"] in ids(p["sku"])
    assert o["id"] in ids(p["sku"].lower())
    assert o["id"] in ids(q["name"].replace(" ", "%20"))
    assert o["id"] in ids("Searchy")
    assert o["id"] in ids(o["reference"].replace("/", "%2F"))
    assert ids("NOPE" + uid()) == []


def test_move_search_by_product_only_shows_that_product(api):
    p, q = product(api), product(api)
    o = make_op(api, "IN", [(p, 2), (q, 3)])
    act(api, o["id"], "todo")
    act(api, o["id"], "validate")
    rows = ok(api.get(f"/moves?q={p['sku']}"))
    assert len(rows) == 1 and p["sku"] in rows[0]["product"]
    both = ok(api.get(f"/moves?q={o['reference'].replace('/', '%2F')}"))
    assert len(both) == 2  # searching the reference keeps every line


# ---------------------------------------------------------------- dashboard filters
def test_dashboard_document_type_filter(api):
    default = ok(api.get("/dashboard"))
    assert [c["type"] for c in default["cards"]] == ["IN", "OUT", "INT"]
    assert [c["type"] for c in ok(api.get("/dashboard?doc_type=OUT"))["cards"]] == ["OUT"]
    adj = ok(api.get("/dashboard?doc_type=ADJ"))["cards"]
    assert [c["type"] for c in adj] == ["ADJ"] and adj[0]["to_process"] >= 1


def test_dashboard_status_and_scope_filters(api):
    p = product(api, stock=5)
    o = make_op(api, "OUT", [(p, 1)])
    act(api, o["id"], "todo")
    ready = ok(api.get("/dashboard?doc_type=OUT&status=ready"))["cards"][0]
    assert ready["by_status"]["ready"] == ready["to_process"] >= 1

    wh, loc = warehouse(api)
    empty = ok(api.get(f"/dashboard?warehouse_id={wh['id']}"))
    assert all(c["to_process"] == 0 for c in empty["cards"])
    assert empty["kpis"]["total_products_in_stock"] == 0  # nothing is stored in the new warehouse
    make_op(api, "IN", [(p, 1)], warehouse_id=wh["id"])
    assert ok(api.get(f"/dashboard?warehouse_id={wh['id']}"))["cards"][0]["to_process"] == 1
    assert ok(api.get(f"/dashboard?location_id={loc['id']}"))["cards"][0]["to_process"] == 1


def test_dashboard_category_filter(api):
    cat = ok(api.post("/categories", json={"name": f"Dash {uid()}"}), 201)
    product(api, stock=4, category_id=cat["id"])
    d = ok(api.get(f"/dashboard?category_id={cat['id']}"))
    assert d["kpis"]["total_products_in_stock"] == 1


def test_stock_free_to_use_excludes_reserved(api):
    p = product(api, stock=10)
    o = make_op(api, "OUT", [(p, 4)])
    act(api, o["id"], "todo")
    row = ok(api.get(f"/stock?q={p['sku']}"))[0]
    assert row["on_hand"] == 10 and row["free_to_use"] == 6
