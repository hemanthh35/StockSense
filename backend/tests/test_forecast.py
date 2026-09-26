from helpers import make_op, ok, product


def deliver(api, p, qty):
    op = make_op(api, "OUT", [(p, qty)])
    for step in ("todo", "pick", "pack", "validate"):
        r = api.post(f"/operations/{op['id']}/{step}")
        assert r.status_code < 300, r.text


def row(api, p, **q):
    rows = ok(api.get("/reports/forecast?days=30" + "".join(f"&{k}={v}" for k, v in q.items())))["rows"]
    return next((r for r in rows if r["product_id"] == p["id"]), None)


def test_days_left_from_recent_deliveries(api):
    p = product(api, stock=100)
    deliver(api, p, 30)  # 1 a day over 30 days, 70 left
    r = row(api, p)
    assert r["sold"] == 30 and r["per_day"] == 1.0 and r["days_left"] == 70 and r["level"] == "ok"
    assert r["runs_out_on"]


def test_critical_and_out_levels(api):
    p = product(api, stock=35)
    deliver(api, p, 30)
    assert row(api, p)["level"] == "critical"
    q = product(api, stock=30)
    deliver(api, q, 30)
    assert row(api, q)["level"] == "out" and row(api, q)["runs_out_on"] is None


def test_unsold_products_are_left_out_and_paging(api):
    p = product(api, stock=5)
    assert row(api, p) is None
    d = ok(api.get("/reports/forecast?page=1&page_size=1"))
    assert d["page_size"] == 1 and len(d["items"]) <= 1 and set(d["counts"]) == {"out", "critical", "soon", "ok"}


def test_level_filter(api):
    p = product(api, stock=35)
    deliver(api, p, 30)
    rows = ok(api.get("/reports/forecast?level=critical&page=1&page_size=100"))["items"]
    assert rows and all(r["level"] == "critical" for r in rows)
