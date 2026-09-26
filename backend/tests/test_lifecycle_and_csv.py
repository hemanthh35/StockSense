import csv
import io

from helpers import act, detail, main_loc, make_op, ok, on_hand, product, receive, uid, warehouse


# ---------------------------------------------------------------- products
def test_archive_blocked_by_stock_then_allowed(api):
    p = product(api, stock=5)
    assert "still holds" in detail(api.post(f"/products/{p['id']}/archive"), 409)
    ok(api.post("/stock/adjust", json={"product_id": p["id"], "location_id": main_loc(api)["id"], "counted_qty": 0}))
    assert ok(api.post(f"/products/{p['id']}/archive"))["active"] is False
    assert p["id"] not in [x["id"] for x in ok(api.get("/products"))]
    assert p["id"] in [x["id"] for x in ok(api.get("/products?include_archived=true"))]


def test_archive_blocked_by_open_documents(api):
    p = product(api)
    make_op(api, "IN", [(p, 3)])  # a draft receipt still needs it
    assert "open document" in detail(api.post(f"/products/{p['id']}/archive"), 409)


def test_archived_product_cannot_be_used_and_can_be_restored(api):
    p = product(api)
    ok(api.post(f"/products/{p['id']}/archive"))
    body = {"type": "IN", "lines": [{"product_id": p["id"], "quantity": 1}]}
    assert "archived" in detail(api.post("/operations", json=body), 422)
    assert p["id"] not in [s["product_id"] for s in ok(api.get("/stock"))]
    assert ok(api.post(f"/products/{p['id']}/restore"))["active"] is True
    ok(api.post("/operations", json=body), 201)


def test_delete_only_when_never_used(api):
    fresh = product(api)
    assert ok(api.delete(f"/products/{fresh['id']}"))["ok"] is True
    assert fresh["id"] not in [x["id"] for x in ok(api.get("/products?include_archived=true"))]

    used = product(api, stock=2)  # its opening-stock adjustment is history
    ok(api.post("/stock/adjust", json={"product_id": used["id"], "location_id": main_loc(api)["id"], "counted_qty": 0}))
    assert "archive it instead" in detail(api.delete(f"/products/{used['id']}"), 409)


# ---------------------------------------------------------------- locations and warehouses
def test_location_archive_and_delete(api):
    wh, loc = warehouse(api)
    p = product(api, stock=3, loc=loc)
    assert "still holds" in detail(api.post(f"/locations/{loc['id']}/archive"), 409)
    ok(api.post("/stock/adjust", json={"product_id": p["id"], "location_id": loc["id"], "counted_qty": 0}))
    assert ok(api.post(f"/locations/{loc['id']}/archive"))["active"] is False
    assert loc["id"] not in [l["id"] for l in ok(api.get("/locations"))]
    body = {"type": "IN", "warehouse_id": wh["id"], "dest_location_id": loc["id"], "lines": [{"product_id": p["id"], "quantity": 1}]}
    assert "archived" in detail(api.post("/operations", json=body), 422)
    ok(api.post(f"/locations/{loc['id']}/restore"))
    ok(api.post("/operations", json=body), 201)

    spare = ok(api.post("/locations", json={"name": "Spare", "short_code": f"S{uid(3)}", "warehouse_id": wh["id"]}), 201)
    assert ok(api.delete(f"/locations/{spare['id']}"))["ok"] is True
    assert "history" in detail(api.delete(f"/locations/{loc['id']}"), 409)


def test_virtual_locations_are_untouchable(api):
    vendor = next(l for l in ok(api.get("/locations")) if l["type"] == "vendor")
    assert api.post(f"/locations/{vendor['id']}/archive").status_code == 404
    assert api.delete(f"/locations/{vendor['id']}").status_code == 404


def test_warehouse_archive_and_delete(api):
    unused, loc = warehouse(api)
    assert ok(api.delete(f"/warehouses/{unused['id']}"))["ok"] is True  # never used -> gone, with its locations
    assert unused["id"] not in [w["id"] for w in ok(api.get("/warehouses?include_archived=true"))]

    wh, loc = warehouse(api)
    p = product(api)
    receive(api, p, 5, warehouse_id=wh["id"])
    assert "still holds" in detail(api.post(f"/warehouses/{wh['id']}/archive"), 409)
    assert "history" in detail(api.delete(f"/warehouses/{wh['id']}"), 409)
    ok(api.post("/stock/adjust", json={"product_id": p["id"], "location_id": loc["id"], "counted_qty": 0}))
    assert ok(api.post(f"/warehouses/{wh['id']}/archive"))["active"] is False
    assert wh["id"] not in [w["id"] for w in ok(api.get("/warehouses"))]
    assert "archived" in detail(api.post("/locations", json={"name": "X", "short_code": "X1", "warehouse_id": wh["id"]}), 422)
    assert ok(api.post(f"/warehouses/{wh['id']}/restore"))["active"] is True


# ---------------------------------------------------------------- CSV export
def read_csv(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    return list(csv.DictReader(io.StringIO(resp.text.lstrip("﻿"))))


def test_export_products_stock_moves_operations(api):
    p = product(api, stock=8)
    o = make_op(api, "OUT", [(p, 2)], contact="Export Co")
    act(api, o["id"], "todo")

    rows = read_csv(api.get("/export/products.csv"))
    mine = next(r for r in rows if r["sku"] == p["sku"])
    assert mine["on_hand"] == "8.0" and mine["tax"] == "GST 18%"

    stock_rows = [r for r in read_csv(api.get(f"/export/stock.csv?q={p['sku']}"))]
    assert stock_rows[0]["on_hand"] == "8.0" and stock_rows[0]["free_to_use"] == "6.0"

    ops = read_csv(api.get("/export/operations.csv?type=OUT&q=Export%20Co"))
    assert ops[0]["reference"] == o["reference"] and float(ops[0]["total"]) == o["total"]

    moves = read_csv(api.get(f"/export/moves.csv?q={p['sku']}"))
    assert {m["type"] for m in moves} == {"ADJ", "OUT"}


def test_export_neutralises_spreadsheet_formulas(api):
    name = f'=HYPERLINK("http://evil","x") {uid()}'
    p = product(api, name=name)
    text = api.get("/export/products.csv").text
    assert "'=HYPERLINK" in text and ',=HYPERLINK' not in text
    ok(api.delete(f"/products/{p['id']}"))


def test_export_has_excel_friendly_bom(api):
    assert api.get("/export/products.csv").text.startswith("﻿")


# ---------------------------------------------------------------- CSV import
def test_import_preview_then_apply(api):
    a, b, dup, bad = (f"IMP{uid()}" for _ in range(4))
    text = (
        "Product,Code,Category,Price,HSN,GST,Opening Stock,Reorder Level\n"
        f"Widget A,{a},Imported Cat,150,8471,18,25,10\n"
        f"Widget B,{b},Imported Cat,99.5,,5,,\n"
        f"Widget A again,{a},,1,,,,\n"          # duplicate SKU in the file
        f"Bad tax,{bad},,10,,GST 99%,,\n"        # unknown tax
    )
    preview = ok(api.post("/products/import", json={"csv": text, "dry_run": True}))
    assert (preview["created"], preview["updated"], preview["skipped"]) == (2, 0, 2)
    assert {e["row"] for e in preview["errors"]} == {4, 5}
    assert "duplicate SKU" in preview["errors"][0]["message"] and "unknown tax" in preview["errors"][1]["message"]
    assert ok(api.get(f"/products?q={a}")) == []  # a preview writes nothing

    done = ok(api.post("/products/import", json={"csv": text, "dry_run": False}))
    assert (done["created"], done["skipped"]) == (2, 2)
    pa = ok(api.get(f"/products?q={a}"))[0]
    assert pa["name"] == "Widget A" and pa["unit_cost"] == 150 and pa["hsn_code"] == "8471"
    assert pa["tax"]["rate"] == 18 and pa["category"] == "Imported Cat" and pa["reorder_min"] == 10
    assert on_hand(api, pa) == 25  # opening stock was booked as an adjustment
    pb = ok(api.get(f"/products?q={b}"))[0]
    assert pb["tax"]["rate"] == 5 and pb["unit_cost"] == 99.5


def test_import_updates_existing_by_sku(api):
    p = product(api, stock=4, unit_cost=100)
    text = f"sku,name,unit_cost,tax\n{p['sku']},Renamed item,175,none\n"
    r = ok(api.post("/products/import", json={"csv": text, "dry_run": False}))
    assert (r["created"], r["updated"]) == (0, 1)
    after = ok(api.get(f"/products?q={p['sku']}"))[0]
    assert after["name"] == "Renamed item" and after["unit_cost"] == 175 and after["tax"] is None
    assert on_hand(api, after) == 4  # untouched


def test_import_reports_bad_numbers_and_missing_columns(api):
    sku = f"IMP{uid()}"
    r = ok(api.post("/products/import", json={"csv": f"name,sku,unit_cost\nX,{sku},abc\nY,{sku}2,-5\n", "dry_run": True}))
    assert r["skipped"] == 2 and "number" in r["errors"][0]["message"] and "negative" in r["errors"][1]["message"]
    assert "'name' and 'sku'" in detail(api.post("/products/import", json={"csv": "title,price\nx,1\n", "dry_run": True}), 422)
    assert "empty" in detail(api.post("/products/import", json={"csv": "", "dry_run": True}), 422)


def test_import_accepts_a_bare_rate_or_tax_name(api):
    a, b = f"IMP{uid()}", f"IMP{uid()}"
    text = f"name,sku,tax\nA,{a},12%\nB,{b},GST 28%\n"
    ok(api.post("/products/import", json={"csv": text, "dry_run": False}))
    assert ok(api.get(f"/products?q={a}"))[0]["tax"]["rate"] == 12
    assert ok(api.get(f"/products?q={b}"))[0]["tax"]["rate"] == 28
