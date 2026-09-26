from helpers import detail, ok, product, uid


def test_barcode_lookup_by_barcode_and_sku(api):
    code = "890" + uid(9)
    p = product(api, stock=6, barcode=code)
    assert p["barcode"] == code
    for key in (code, p["sku"], p["sku"].lower()):
        r = ok(api.get(f"/products/lookup?code={key}"))
        assert r["product_id"] == p["id"] and r["on_hand"] == 6 and r["locations"]


def test_unknown_code_is_404(api):
    assert "No product" in detail(api.get("/products/lookup?code=NOPE-" + uid()), 404)


def test_barcode_must_be_unique_and_not_a_sku(api):
    code = "891" + uid(9)
    a = product(api, barcode=code)
    sku = f"B{uid()}"
    assert "already used" in detail(api.post("/products", json={"name": "Dup", "sku": sku, "unit_cost": 1, "barcode": code}), 409)
    assert "already used" in detail(api.post("/products", json={"name": "Dup", "sku": sku, "unit_cost": 1, "barcode": a["sku"]}), 409)
    b = product(api)
    body = {"name": b["name"], "sku": b["sku"], "unit_cost": 1, "barcode": code, "version": b["version"]}
    assert "already used" in detail(api.put(f"/products/{b['id']}", json=body), 409)


def test_search_finds_by_barcode_and_can_be_cleared(api):
    code = "892" + uid(9)
    p = product(api, barcode=code)
    assert [x["id"] for x in ok(api.get(f"/products?q={code}"))] == [p["id"]]
    assert [x["product_id"] for x in ok(api.get(f"/stock?q={code}"))] == [p["id"]]
    body = {"name": p["name"], "sku": p["sku"], "unit_cost": 100, "barcode": "", "version": p["version"]}
    assert ok(api.put(f"/products/{p['id']}", json=body))["barcode"] is None
