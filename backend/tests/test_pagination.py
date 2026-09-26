from helpers import act, make_op, ok, product, receive, uid


def ids_of(items, key="id"):
    return [i[key] for i in items]


def test_products_paged_envelope_and_pages(api):
    tag = f"PG{uid()}"
    made = [product(api, name=f"{tag} item {i:02d}") for i in range(12)]
    first = ok(api.get(f"/products?q={tag}&page=1&page_size=5"))
    assert set(first) == {"items", "total", "page", "page_size", "pages"}
    assert (first["total"], first["page"], first["page_size"], first["pages"]) == (12, 1, 5, 3)
    assert [p["name"] for p in first["items"]] == [f"{tag} item {i:02d}" for i in range(5)]
    last = ok(api.get(f"/products?q={tag}&page=3&page_size=5"))
    assert len(last["items"]) == 2 and last["page"] == 3
    empty = ok(api.get(f"/products?q={tag}&page=9&page_size=5"))
    assert empty["items"] == [] and empty["total"] == 12  # past the end is empty, not an error

    # every page together is exactly the unpaged list
    walked = []
    for n in (1, 2, 3):
        walked += ids_of(ok(api.get(f"/products?q={tag}&page={n}&page_size=5"))["items"])
    assert walked == ids_of(ok(api.get(f"/products?q={tag}"))) == [p["id"] for p in made]


def test_without_page_the_plain_list_is_unchanged(api):
    assert isinstance(ok(api.get("/products")), list)
    assert isinstance(ok(api.get("/operations")), list)
    assert isinstance(ok(api.get("/moves")), list)
    assert isinstance(ok(api.get("/stock")), list)
    assert isinstance(ok(api.get("/parties")), list)


def test_page_parameters_are_validated(api):
    assert api.get("/products?page=0").status_code == 422
    assert api.get("/products?page=1&page_size=0").status_code == 422
    assert api.get("/products?page=1&page_size=201").status_code == 422
    assert api.get("/products?page=abc").status_code == 422


def test_products_by_ids_for_the_order_screen(api):
    a, b, _c = product(api), product(api), product(api)
    got = ok(api.get(f"/products?ids={a['id']},{b['id']}"))
    assert sorted(ids_of(got)) == sorted([a["id"], b["id"]]) and got[0]["tax"] is not None
    assert api.get("/products?ids=1,x").status_code == 422


def test_stock_paged_matches_unpaged(api):
    tag = f"ST{uid()}"
    for i in range(7):
        product(api, stock=i + 1, name=f"{tag} p{i}")
    paged = ok(api.get(f"/stock?q={tag}&page=2&page_size=3"))
    full = ok(api.get(f"/stock?q={tag}"))
    assert paged["total"] == len(full) == 7 and paged["pages"] == 3
    assert paged["items"] == full[3:6]
    assert paged["items"][0]["locations"] and paged["items"][0]["on_hand"] == paged["items"][0]["free_to_use"]


def test_operations_paged_with_filters(api):
    p = product(api)
    tag = f"OP{uid()}"
    docs = [make_op(api, "IN", [(p, 1)], contact=f"{tag} vendor") for _ in range(6)]
    for d in docs[:2]:
        act(api, d["id"], "todo")
    page = ok(api.get(f"/operations?q={tag}&page=1&page_size=4"))
    assert page["total"] == 6 and len(page["items"]) == 4
    assert ids_of(page["items"]) == sorted(ids_of(page["items"]), reverse=True)  # newest first
    ready = ok(api.get(f"/operations?q={tag}&status=ready&page=1&page_size=10"))
    assert ready["total"] == 2 and {o["status"] for o in ready["items"]} == {"ready"}
    assert ok(api.get(f"/operations?q={tag}&type=OUT&page=1"))["total"] == 0
    assert "total" in page["items"][0] and page["items"][0]["reference"]  # rows still carry their totals


def test_moves_paged_matches_unpaged(api):
    tag = f"MV{uid()}"
    p = product(api, name=f"{tag} widget")
    for _ in range(4):
        receive(api, p, 2)
    full = ok(api.get(f"/moves?q={tag}"))
    paged = ok(api.get(f"/moves?q={tag}&page=2&page_size=3"))
    assert paged["total"] == len(full) == 4 and paged["items"] == full[3:6]
    assert ok(api.get(f"/moves?q={tag}&direction=in&page=1"))["total"] == 4
    assert ok(api.get(f"/moves?q={tag}&direction=out&page=1"))["total"] == 0


def test_moves_direction_filter_in_sql(api):
    p = product(api, stock=10)
    o = make_op(api, "OUT", [(p, 2)])
    act(api, o["id"], "todo")
    for a in ("pick", "pack", "validate"):
        act(api, o["id"], a)
    out = ok(api.get(f"/moves?q={p['sku']}&direction=out"))
    inn = ok(api.get(f"/moves?q={p['sku']}&direction=in"))
    assert [m["direction"] for m in out] == ["out"] and [m["direction"] for m in inn] == ["in"]


def test_parties_paged(api):
    from helpers import party
    tag = f"PT{uid()}"
    for i in range(5):
        ok(api.post("/parties", json={"name": f"{tag} {i}", "kind": "both"}), 201)
    page = ok(api.get(f"/parties?q={tag}&page=1&page_size=2"))
    assert page["total"] == 5 and len(page["items"]) == 2 and page["items"][0]["documents"] == 0


def test_reports_paged_keep_their_totals(api):
    tag = f"RP{uid()}"
    cat = ok(api.post("/categories", json={"name": tag}), 201)
    for i in range(6):
        product(api, stock=2, unit_cost=100, cost_price=40, category_id=cat["id"], name=f"{tag} {i}")
    full = ok(api.get(f"/reports/valuation?category_id={cat['id']}"))
    page = ok(api.get(f"/reports/valuation?category_id={cat['id']}&page=2&page_size=4"))
    assert page["total"] == 6 and len(page["rows"]) == 2 and page["items"] == page["rows"]
    assert page["totals"] == full["totals"] == {"on_hand": 12, "value": 480, "retail_value": 1200, "potential_margin": 720}
    assert page["by_category"] == full["by_category"]


def test_margin_paged(api):
    from helpers import ship
    tag = f"MG{uid()}"
    cat = ok(api.post("/categories", json={"name": tag}), 201)
    for i in range(3):
        p = product(api, stock=5, unit_cost=200, cost_price=50, category_id=cat["id"])
        o = make_op(api, "OUT", [(p, 1 + i)])
        act(api, o["id"], "todo")
        ship(api, o["id"])
    page = ok(api.get(f"/reports/margin?category_id={cat['id']}&page=1&page_size=2"))
    assert page["total"] == 3 and len(page["rows"]) == 2
    assert page["totals"]["revenue"] == 200 * (1 + 2 + 3) and page["totals"]["cost"] == 50 * 6
    assert page["rows"][0]["margin"] >= page["rows"][1]["margin"]  # biggest earner first


def test_the_dashboard_matches_what_the_lists_say(api):
    p = product(api, stock=5, reorder_min=50, reorder_qty=25)
    d = ok(api.get("/dashboard"))
    assert d["kpis"]["pending_receipts"] == len([o for o in ok(api.get("/operations?type=IN")) if o["status"] in ("draft", "waiting", "ready")])
    assert d["kpis"]["pending_deliveries"] == len([o for o in ok(api.get("/operations?type=OUT")) if o["status"] in ("draft", "waiting", "ready")])
    assert d["reorder_count"] == len(ok(api.get("/reorder/suggestions")))
    assert ok(api.get("/reorder/suggestions?page=1&page_size=1"))["total"] == d["reorder_count"]
