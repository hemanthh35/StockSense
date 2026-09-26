import csv
import io

from helpers import act, main_loc, make_op, ok, on_hand, product, receive, ship, stock_locations, uid, warehouse


def avg(api, p) -> float:
    return next(x for x in ok(api.get("/products?include_archived=true")) if x["id"] == p["id"])["avg_cost"]


def value_row(api, p):
    rows = ok(api.get(f"/reports/valuation?q={p['sku']}"))["rows"]
    return rows[0] if rows else None


def test_receipts_default_to_the_purchase_price_and_deliveries_to_the_sales_price(api):
    p = product(api, unit_cost=100, cost_price=60, stock=5)
    assert make_op(api, "IN", [(p, 1)])["lines"][0]["unit_price"] == 60
    assert make_op(api, "OUT", [(p, 1)])["lines"][0]["unit_price"] == 100
    plain = product(api, unit_cost=80)  # no purchase price set -> receipts fall back to the sales price
    assert make_op(api, "IN", [(plain, 1)])["lines"][0]["unit_price"] == 80


def test_opening_stock_starts_at_the_purchase_price(api):
    p = product(api, unit_cost=100, cost_price=60, stock=10)
    assert avg(api, p) == 60
    r = value_row(api, p)
    assert r["on_hand"] == 10 and r["avg_cost"] == 60 and r["value"] == 600 and r["retail_value"] == 1000


def test_weighted_average_cost_on_receipts(api):
    p = product(api, unit_cost=300, cost_price=100, stock=10)
    receive(api, p, 10, )  # bought at the default 100
    assert avg(api, p) == 100
    o = ok(api.post("/operations", json={"type": "IN", "lines": [{"product_id": p["id"], "quantity": 20, "unit_price": 160}]}), 201)
    act(api, o["id"], "todo")
    act(api, o["id"], "validate")
    # (20 units @100 + 20 units @160) / 40 = 130
    assert avg(api, p) == 130
    assert value_row(api, p)["value"] == 40 * 130


def test_a_receipt_into_empty_stock_resets_the_average(api):
    p = product(api, unit_cost=300, cost_price=100)
    o = ok(api.post("/operations", json={"type": "IN", "lines": [{"product_id": p["id"], "quantity": 5, "unit_price": 250}]}), 201)
    act(api, o["id"], "todo")
    act(api, o["id"], "validate")
    assert avg(api, p) == 250


def test_deliveries_record_the_cost_and_leave_the_average_alone(api):
    p = product(api, unit_cost=300, cost_price=100, stock=10)
    out = make_op(api, "OUT", [(p, 4)])
    act(api, out["id"], "todo")
    done = ship(api, out["id"])
    assert done["lines"][0]["cost_price"] == 100 and avg(api, p) == 100
    assert on_hand(api, p) == 6 and value_row(api, p)["value"] == 600


def test_transfers_do_not_change_the_average(api):
    s1, s2 = stock_locations(api)[:2]
    p = product(api, unit_cost=300, cost_price=100, stock=10, loc=s1)
    t = make_op(api, "INT", [(p, 4)], source_location_id=s1["id"], dest_location_id=s2["id"])
    act(api, t["id"], "todo")
    act(api, t["id"], "validate")
    assert avg(api, p) == 100 and value_row(api, p)["value"] == 1000


def test_positive_adjustments_value_at_the_purchase_price(api):
    p = product(api, unit_cost=300, cost_price=100, stock=10)
    ok(api.post("/stock/adjust", json={"product_id": p["id"], "location_id": main_loc(api)["id"], "counted_qty": 14}))
    assert avg(api, p) == 100 and value_row(api, p)["value"] == 1400


def test_editing_the_price_of_an_empty_product_rebases_the_average(api):
    p = product(api, unit_cost=300, cost_price=100)
    ok(api.put(f"/products/{p['id']}", json={"name": p["name"], "sku": p["sku"], "unit_cost": 300, "cost_price": 120}))
    assert avg(api, p) == 120
    stocked = product(api, unit_cost=300, cost_price=100, stock=5)
    ok(api.put(f"/products/{stocked['id']}", json={"name": stocked["name"], "sku": stocked["sku"], "unit_cost": 300, "cost_price": 999}))
    assert avg(api, stocked) == 100  # stock on the shelf keeps its real cost


def test_valuation_report_filters_and_totals(api):
    cat = ok(api.post("/categories", json={"name": f"Val {uid()}"}), 201)
    a = product(api, unit_cost=200, cost_price=100, stock=10, category_id=cat["id"])
    b = product(api, unit_cost=50, cost_price=20, stock=5, category_id=cat["id"])
    empty = product(api, category_id=cat["id"])
    rep = ok(api.get(f"/reports/valuation?category_id={cat['id']}"))
    assert [r["product_id"] for r in rep["rows"]] == [a["id"], b["id"]]  # biggest value first, empty stock hidden
    assert rep["totals"]["value"] == 1000 + 100 and rep["totals"]["retail_value"] == 2000 + 250
    assert rep["totals"]["potential_margin"] == (2000 + 250) - (1000 + 100)
    assert rep["by_category"] == [{"category": cat["name"], "value": 1100}]
    with_zero = ok(api.get(f"/reports/valuation?category_id={cat['id']}&include_zero=true"))
    assert empty["id"] in [r["product_id"] for r in with_zero["rows"]]


def test_valuation_respects_the_warehouse(api):
    wh, loc = warehouse(api)
    p = product(api, unit_cost=100, cost_price=50, stock=4, loc=loc)
    here = ok(api.get(f"/reports/valuation?warehouse_id={wh['id']}"))
    assert [r["product_id"] for r in here["rows"]] == [p["id"]] and here["totals"]["value"] == 200


def test_dashboard_shows_stock_value(api):
    before = ok(api.get("/dashboard"))["kpis"]["stock_value"]
    product(api, unit_cost=500, cost_price=200, stock=10)
    assert ok(api.get("/dashboard"))["kpis"]["stock_value"] == before + 2000


def test_margin_report(api):
    cat = ok(api.post("/categories", json={"name": f"Mar {uid()}"}), 201)
    p = product(api, unit_cost=300, cost_price=100, stock=10, category_id=cat["id"])
    out = make_op(api, "OUT", [(p, 4)])  # sells at 300, costs 100
    act(api, out["id"], "todo")
    ship(api, out["id"])
    rep = ok(api.get(f"/reports/margin?days=30&category_id={cat['id']}"))
    row = rep["rows"][0]
    assert (row["quantity"], row["revenue"], row["cost"], row["margin"], row["margin_pct"]) == (4, 1200, 400, 800, 66.7)
    assert rep["totals"] == {"revenue": 1200, "cost": 400, "margin": 800, "margin_pct": 66.7}
    # a delivery that hasn't been validated yet is not revenue
    make_op(api, "OUT", [(p, 1)])
    assert ok(api.get(f"/reports/margin?days=30&category_id={cat['id']}"))["totals"]["revenue"] == 1200


def test_margin_uses_the_average_at_the_time_of_the_sale(api):
    cat = ok(api.post("/categories", json={"name": f"Mar {uid()}"}), 201)
    p = product(api, unit_cost=300, cost_price=100, stock=10, category_id=cat["id"])
    first = make_op(api, "OUT", [(p, 2)])
    act(api, first["id"], "todo")
    ship(api, first["id"])  # cost 100
    dear = ok(api.post("/operations", json={"type": "IN", "lines": [{"product_id": p["id"], "quantity": 8, "unit_price": 200}]}), 201)
    act(api, dear["id"], "todo")
    act(api, dear["id"], "validate")  # 8 left @100 + 8 @200 -> avg 150
    second = make_op(api, "OUT", [(p, 2)])
    act(api, second["id"], "todo")
    ship(api, second["id"])  # cost 150
    row = ok(api.get(f"/reports/margin?category_id={cat['id']}"))["rows"][0]
    assert row["cost"] == 2 * 100 + 2 * 150


def test_valuation_and_margin_exports(api):
    p = product(api, unit_cost=200, cost_price=100, stock=3)
    r = api.get(f"/export/valuation.csv?q={p['sku']}")
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    assert rows[0]["sku"] == p["sku"] and float(rows[0]["stock_value"]) == 300
    assert rows[-1]["sku"] == "TOTAL" and float(rows[-1]["stock_value"]) == 300
    m = api.get("/export/margin.csv?days=30")
    assert m.status_code == 200 and m.text.lstrip("﻿").startswith("sku,product,quantity,revenue,cost,margin,margin_pct")


def test_product_import_understands_purchase_and_sales_prices(api):
    sku = f"IMP{uid()}"
    text = f"name,sku,price,cost,opening stock\nCosted,{sku},250,140,6\n"
    ok(api.post("/products/import", json={"csv": text, "dry_run": False}))
    p = ok(api.get(f"/products?q={sku}"))[0]
    assert p["unit_cost"] == 250 and p["cost_price"] == 140 and p["avg_cost"] == 140
    assert value_row(api, p)["value"] == 6 * 140
