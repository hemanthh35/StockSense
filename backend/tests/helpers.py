import uuid


def uid(n: int = 6) -> str:
    return uuid.uuid4().hex[:n].upper()


def ok(resp, code: int | None = None):
    """Assert the status (any 2xx by default) and return the JSON body."""
    if code is None:
        assert resp.status_code < 300, f"{resp.status_code}: {resp.text}"
    else:
        assert resp.status_code == code, f"expected {code}, got {resp.status_code}: {resp.text}"
    return resp.json()


def detail(resp, code: int) -> str:
    """Assert an error status and return the message."""
    assert resp.status_code == code, f"expected {code}, got {resp.status_code}: {resp.text}"
    return resp.json()["detail"]


def stock_locations(api, warehouse_code: str = "WH") -> list[dict]:
    whs = ok(api.get("/warehouses"))
    wh = next(w for w in whs if w["short_code"] == warehouse_code)
    return ok(api.get(f"/locations?warehouse_id={wh['id']}&internal_only=true"))


def main_loc(api) -> dict:
    return stock_locations(api)[0]


def product(api, stock: float = 0, loc: dict | None = None, **kw) -> dict:
    sku = f"T{uid()}"
    body = {"name": f"Test {sku}", "sku": sku, "unit_cost": 100, **kw}
    if stock:
        body["initial_stock"] = stock
        body["initial_location_id"] = (loc or main_loc(api))["id"]
    return ok(api.post("/products", json=body), 201)


def on_hand(api, p: dict) -> float:
    rows = ok(api.get(f"/stock?q={p['sku']}"))
    return rows[0]["on_hand"] if rows else 0


def make_op(api, op_type: str, lines: list[tuple[dict, float]], **kw) -> dict:
    body = {"type": op_type, "lines": [{"product_id": p["id"], "quantity": q} for p, q in lines], **kw}
    return ok(api.post("/operations", json=body), 201)


def act(api, op_id: int, action: str, code: int | None = None):
    return ok(api.post(f"/operations/{op_id}/{action}"), code)


def receive(api, p: dict, qty: float, **kw) -> dict:
    """Create, ready and validate a receipt."""
    o = make_op(api, "IN", [(p, qty)], **kw)
    act(api, o["id"], "todo")
    return act(api, o["id"], "validate")


def ship(api, op_id: int) -> dict:
    """Walk a ready delivery through pick, pack and validate."""
    act(api, op_id, "pick")
    act(api, op_id, "pack")
    return act(api, op_id, "validate")


def warehouse(api, with_location: bool = True) -> tuple[dict, dict | None]:
    wh = ok(api.post("/warehouses", json={"name": f"Test WH {uid(3)}", "short_code": f"W{uid(4)}"}), 201)
    loc = None
    if with_location:
        loc = ok(api.post("/locations", json={"name": "Rack", "short_code": f"R{uid(3)}", "warehouse_id": wh["id"]}), 201)
    return wh, loc


def party(api, kind: str = "both", **kw) -> dict:
    return ok(api.post("/parties", json={"name": f"Party {uid()}", "kind": kind, **kw}), 201)
