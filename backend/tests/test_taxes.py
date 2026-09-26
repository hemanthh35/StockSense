from helpers import act, detail, make_op, ok, product, receive, uid


def taxes(api):
    return {t["name"]: t for t in ok(api.get("/taxes?include_inactive=true"))}


def test_gst_slabs_are_seeded_with_a_default(api):
    t = taxes(api)
    for rate in (0, 5, 12, 18, 28):
        assert t[f"GST {rate}%"]["rate"] == rate
    assert [x["name"] for x in t.values() if x["is_default"]] == ["GST 18%"]


def test_product_tax_resolution(api):
    default = product(api)
    assert default["tax"]["name"] == "GST 18%"  # nothing chosen -> global default

    cat = ok(api.post("/categories", json={"name": f"Cat {uid()}"}), 201)
    ok(api.put(f"/category-taxes/{cat['id']}", json={"default_tax_id": taxes(api)["GST 5%"]["id"]}))
    in_cat = product(api, category_id=cat["id"])
    assert in_cat["tax"]["rate"] == 5  # category default beats the global default

    explicit = product(api, category_id=cat["id"], tax_id=taxes(api)["GST 28%"]["id"])
    assert explicit["tax"]["rate"] == 28

    none = product(api, tax_id=0)
    assert none["tax"] is None


def test_new_tax_can_be_added_and_used_immediately(api):
    name = f"GST 40% {uid(3)}"
    t = ok(api.post("/taxes", json={"name": name, "rate": 40, "kind": "GST"}), 201)
    p = product(api, tax_id=t["id"])
    assert p["tax"]["rate"] == 40


def test_tax_validation(api):
    name = f"Dup {uid()}"
    ok(api.post("/taxes", json={"name": name, "rate": 3, "kind": "OTHER"}), 201)
    assert "already exists" in detail(api.post("/taxes", json={"name": name, "rate": 3, "kind": "OTHER"}), 409)
    assert "between 0 and 100" in detail(api.post("/taxes", json={"name": f"X{uid()}", "rate": 101}), 422)
    assert "GST or OTHER" in detail(api.post("/taxes", json={"name": f"Y{uid()}", "rate": 1, "kind": "VAT"}), 422)


def test_only_one_default_tax(api):
    t = ok(api.post("/taxes", json={"name": f"Def {uid()}", "rate": 9, "kind": "OTHER", "is_default": True}), 201)
    defaults = [x for x in taxes(api).values() if x["is_default"]]
    assert [d["id"] for d in defaults] == [t["id"]]
    # put the seeded default back so other tests keep their assumptions
    gst18 = taxes(api)["GST 18%"]
    ok(api.put(f"/taxes/{gst18['id']}", json={"name": "GST 18%", "rate": 18, "kind": "GST", "active": True, "is_default": True}))
    assert [x["name"] for x in taxes(api).values() if x["is_default"]] == ["GST 18%"]


def test_inactive_tax_is_not_offered(api):
    t = ok(api.post("/taxes", json={"name": f"Old {uid()}", "rate": 2, "kind": "OTHER", "active": False}), 201)
    assert t["id"] not in [x["id"] for x in ok(api.get("/taxes"))]
    assert t["id"] in [x["id"] for x in ok(api.get("/taxes?include_inactive=true"))]


def test_line_prefills_price_and_tax_and_totals_add_up(api):
    p = product(api, unit_cost=100)  # 18% by default
    o = make_op(api, "IN", [(p, 3)])
    line = o["lines"][0]
    assert (line["unit_price"], line["tax_rate"], line["tax_name"]) == (100, 18, "GST 18%")
    assert (o["subtotal"], o["tax_total"], o["total"]) == (300, 54, 354)
    assert o["tax_breakdown"] == [{"name": "GST 18%", "rate": 18, "base": 300, "amount": 54}]


def test_price_override_on_a_line(api):
    p = product(api, unit_cost=100)
    o = ok(api.post("/operations", json={"type": "IN", "lines": [{"product_id": p["id"], "quantity": 2, "unit_price": 250}]}), 201)
    assert o["lines"][0]["unit_price"] == 250 and o["subtotal"] == 500


def test_mixed_rates_are_grouped(api):
    a = product(api, unit_cost=100, tax_id=taxes(api)["GST 5%"]["id"])
    b = product(api, unit_cost=200, tax_id=taxes(api)["GST 18%"]["id"])
    c = product(api, unit_cost=50, tax_id=0)
    o = make_op(api, "IN", [(a, 1), (b, 1), (c, 2)])
    assert o["subtotal"] == 400 and o["tax_total"] == 5 + 36 and o["total"] == 441
    assert [g["name"] for g in o["tax_breakdown"]] == ["GST 5%", "GST 18%"]


def test_validated_documents_keep_the_rate_they_were_created_with(api):
    tax = ok(api.post("/taxes", json={"name": f"Snap {uid()}", "rate": 7, "kind": "OTHER"}), 201)
    p = product(api, unit_cost=100, tax_id=tax["id"])
    done = receive(api, p, 10)
    assert done["tax_total"] == 70

    ok(api.put(f"/taxes/{tax['id']}", json={"name": tax["name"], "rate": 10, "kind": "OTHER", "active": True, "is_default": False}))
    assert ok(api.get(f"/operations/{done['id']}"))["tax_total"] == 70  # history unchanged
    fresh = make_op(api, "IN", [(p, 10)])
    assert fresh["tax_total"] == 100  # new documents use the new rate


def test_drafts_pick_up_a_changed_rate_when_saved_again(api):
    tax = ok(api.post("/taxes", json={"name": f"Draft {uid()}", "rate": 4, "kind": "OTHER"}), 201)
    p = product(api, unit_cost=100, tax_id=tax["id"])
    o = make_op(api, "IN", [(p, 1)])
    assert o["tax_total"] == 4
    ok(api.put(f"/taxes/{tax['id']}", json={"name": tax["name"], "rate": 6, "kind": "OTHER", "active": True, "is_default": False}))
    resaved = ok(api.put(f"/operations/{o['id']}", json={"type": "IN", "lines": [{"product_id": p["id"], "quantity": 1}]}))
    assert resaved["tax_total"] == 6
