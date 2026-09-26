from helpers import act, detail, main_loc, make_op, ok, party, product, stock_locations, uid, warehouse


def forbidden(resp) -> str:
    return detail(resp, 403)


# ---------------------------------------------------------------- who is who
def test_first_user_is_admin_and_later_signups_are_staff(api, make_user):
    assert ok(api.get("/auth/me"))["role"] == "admin"
    assert ok(make_user("staff").get("/auth/me"))["role"] == "staff"
    assert ok(make_user("manager").get("/auth/me"))["role"] == "manager"


def test_staff_can_look_but_not_change_the_catalogue(api, make_user):
    staff = make_user("staff")
    for path in ("/products", "/parties", "/operations", "/stock", "/moves", "/dashboard", "/warehouses", "/locations", "/taxes", "/categories"):
        assert staff.get(path).status_code == 200, path
    assert "manager" in forbidden(staff.post("/products", json={"name": "x", "sku": f"S{uid()}"}))
    assert "manager" in forbidden(staff.post("/parties", json={"name": f"P {uid()}"}))
    assert "manager" in forbidden(staff.post("/categories", json={"name": f"C {uid()}"}))
    assert "manager" in forbidden(staff.post("/products/import", json={"csv": "name,sku\nA,B", "dry_run": True}))
    assert "manager" in forbidden(staff.post("/reorder/receipt", json={}))
    p = product(api)
    assert forbidden(staff.put(f"/products/{p['id']}", json={"name": "hack", "sku": p["sku"]}))
    assert forbidden(staff.post(f"/products/{p['id']}/archive"))
    assert forbidden(staff.delete(f"/products/{p['id']}"))


def test_only_admins_touch_settings(api, make_user):
    manager = make_user("manager")
    assert "admin" in forbidden(manager.post("/warehouses", json={"name": "W", "short_code": f"X{uid(3)}"}))
    assert "admin" in forbidden(manager.post("/taxes", json={"name": f"T{uid()}", "rate": 1}))
    assert forbidden(manager.put("/category-taxes/1", json={"default_tax_id": None}))
    wh, loc = warehouse(api)
    assert forbidden(manager.post("/locations", json={"name": "L", "short_code": "L1", "warehouse_id": wh["id"]}))
    assert forbidden(manager.post(f"/warehouses/{wh['id']}/archive"))
    assert forbidden(manager.delete(f"/locations/{loc['id']}"))
    assert forbidden(manager.get("/users"))


def test_managers_run_the_business(api, make_user):
    m = make_user("manager")
    p = ok(m.post("/products", json={"name": "Mgr product", "sku": f"M{uid()}", "initial_stock": 5}), 201)
    ok(m.post("/parties", json={"name": f"Mgr party {uid()}"}), 201)
    ok(m.post("/categories", json={"name": f"Mgr cat {uid()}"}), 201)
    o = ok(m.post("/operations", json={"type": "OUT", "lines": [{"product_id": p["id"], "quantity": 1}]}), 201)
    ok(m.post(f"/operations/{o['id']}/duplicate"))
    ok(m.post(f"/operations/{o['id']}/cancel"))
    assert ok(m.get("/audit?page=1"))["total"] >= 1  # managers can read the activity log


def test_staff_work_documents_through_their_stages_but_cannot_create_receipts_or_deliveries(api, make_user):
    staff = make_user("staff")
    p = product(api, stock=10)
    body = {"type": "OUT", "lines": [{"product_id": p["id"], "quantity": 2}]}
    assert "manager" in forbidden(staff.post("/operations", json=body))
    assert forbidden(staff.post("/operations", json={"type": "IN", "lines": []}))

    delivery = make_op(api, "OUT", [(p, 2)])  # a manager/admin prepares it...
    assert ok(staff.post(f"/operations/{delivery['id']}/todo"))["status"] == "ready"  # ...staff pick, pack and ship it
    ok(staff.post(f"/operations/{delivery['id']}/pick"))
    ok(staff.post(f"/operations/{delivery['id']}/pack"))
    assert ok(staff.post(f"/operations/{delivery['id']}/validate"))["status"] == "done"

    other = make_op(api, "OUT", [(p, 1)])
    assert forbidden(staff.put(f"/operations/{other['id']}", json={"type": "OUT", "lines": []}))
    assert forbidden(staff.post(f"/operations/{other['id']}/cancel"))
    assert forbidden(staff.post(f"/operations/{other['id']}/duplicate"))


def test_staff_run_internal_transfers_and_count_stock(api, make_user):
    staff = make_user("staff")
    s1, s2 = stock_locations(api)[:2]
    p = product(api, stock=8, loc=s1)
    t = ok(staff.post("/operations", json={"type": "INT", "source_location_id": s1["id"], "dest_location_id": s2["id"],
                                          "lines": [{"product_id": p["id"], "quantity": 3}]}), 201)
    ok(staff.put(f"/operations/{t['id']}", json={"type": "INT", "source_location_id": s1["id"], "dest_location_id": s2["id"],
                                                "lines": [{"product_id": p["id"], "quantity": 4}]}))
    ok(staff.post(f"/operations/{t['id']}/todo"))
    assert ok(staff.post(f"/operations/{t['id']}/validate"))["status"] == "done"
    counted = ok(staff.post("/stock/adjust", json={"product_id": p["id"], "location_id": s1["id"], "counted_qty": 3}))
    assert counted["difference"] == -1
    spare = ok(staff.post("/operations", json={"type": "INT", "source_location_id": s1["id"], "dest_location_id": s2["id"], "lines": []}), 201)
    assert ok(staff.post(f"/operations/{spare['id']}/cancel"))["status"] == "cancelled"


def test_staff_cannot_read_the_activity_log_or_users(make_user):
    staff = make_user("staff")
    assert forbidden(staff.get("/audit"))
    assert forbidden(staff.get("/users"))


# ---------------------------------------------------------------- user administration
def test_admin_manages_roles_and_deactivation(api, make_user, anon):
    m = make_user("staff")
    me = ok(m.get("/auth/me"))
    users = ok(api.get("/users?page=1&page_size=100"))
    assert me["id"] in ids(users["items"]) and users["total"] >= 3
    up = ok(api.put(f"/users/{me['id']}", json={"role": "manager", "active": True}))
    assert up["role"] == "manager"
    assert ok(m.post("/categories", json={"name": f"Now allowed {uid()}"}), 201)  # takes effect immediately
    assert "one of" in detail(api.put(f"/users/{me['id']}", json={"role": "wizard", "active": True}), 422)

    ok(api.put(f"/users/{me['id']}", json={"role": "manager", "active": False}))
    assert "deactivated" in detail(m.get("/products"), 401)  # a deactivated person's token stops working at once


def ids(items):
    return [i["id"] for i in items]


def test_the_last_admin_cannot_be_removed(api):
    me = ok(api.get("/auth/me"))
    assert "at least one active administrator" in detail(api.put(f"/users/{me['id']}", json={"role": "staff", "active": True}), 409)
    assert "at least one active administrator" in detail(api.put(f"/users/{me['id']}", json={"role": "admin", "active": False}), 409)
    assert api.put("/users/999999", json={"role": "staff", "active": True}).status_code == 404


def test_a_second_admin_makes_demotion_possible(api, make_user):
    other = make_user("admin")
    oid = ok(other.get("/auth/me"))["id"]
    ok(api.put(f"/users/{oid}", json={"role": "manager", "active": True}))  # fine: pytest_admin is still there


def test_deactivated_login_is_refused(api, anon):
    from conftest import PASSWORD
    login = f"gone{uid(4).lower()}"
    r = ok(anon.post("/auth/signup", json={"login_id": login, "email": f"{login}@example.com", "password": PASSWORD, "confirm_password": PASSWORD}), 201)
    ok(api.put(f"/users/{r['user']['id']}", json={"role": "staff", "active": False}))
    assert "deactivated" in detail(anon.post("/auth/login", json={"login_id": login, "password": PASSWORD}), 403)


# ---------------------------------------------------------------- audit trail
def audit(api, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return ok(api.get(f"/audit?page=1&page_size=100&{qs}"))["items"]


def test_creating_and_editing_a_product_is_recorded_with_the_changes(api):
    p = product(api, unit_cost=100)
    ok(api.put(f"/products/{p['id']}", json={"name": p["name"], "sku": p["sku"], "unit_cost": 150, "reorder_min": 5}))
    rows = audit(api, entity="product", entity_id=p["id"])
    assert [r["action"] for r in rows] == ["update", "create"]  # newest first
    assert rows[0]["user"] == "pytest_admin"
    assert rows[0]["changes"]["unit_cost"] == [100, 150] and rows[0]["changes"]["reorder_min"] == [0, 5]
    assert rows[0]["label"].startswith(p["sku"])


def test_an_edit_that_changes_nothing_leaves_no_trace(api):
    p = product(api)
    before = len(audit(api, entity="product", entity_id=p["id"]))
    same = ok(api.put(f"/products/{p['id']}", json={"name": p["name"], "sku": p["sku"], "unit_cost": p["unit_cost"]}))
    assert len(audit(api, entity="product", entity_id=p["id"])) == before and same["version"] == p["version"]


def test_document_history_follows_the_workflow(api, make_user):
    m = make_user("manager")
    p = product(api, stock=5)
    o = ok(m.post("/operations", json={"type": "OUT", "lines": [{"product_id": p["id"], "quantity": 2}]}), 201)
    ok(m.put(f"/operations/{o['id']}", json={"type": "OUT", "contact": "Changed Co", "lines": [{"product_id": p["id"], "quantity": 3}]}))
    for a in ("todo", "pick", "pack", "validate"):
        ok(m.post(f"/operations/{o['id']}/{a}"))
    hist = ok(api.get(f"/operations/{o['id']}/history"))
    assert [h["action"] for h in hist] == ["validate", "pack", "pick", "todo", "update", "create"]
    edit = next(h for h in hist if h["action"] == "update")
    assert edit["changes"]["contact"] == [None, "Changed Co"] and "lines" in edit["changes"]
    assert {h["user"] for h in hist} == {ok(m.get("/auth/me"))["login_id"]}
    assert api.get("/operations/999999/history").status_code == 404


def test_a_refused_action_is_not_recorded(api):
    p = product(api, stock=5)
    o = make_op(api, "OUT", [(p, 1)])
    act(api, o["id"], "todo")
    before = len(ok(api.get(f"/operations/{o['id']}/history")))
    assert api.post(f"/operations/{o['id']}/validate").status_code == 409  # not packed yet
    assert len(ok(api.get(f"/operations/{o['id']}/history"))) == before


def test_partial_validation_and_duplicates_are_recorded(api):
    p = product(api)
    o = make_op(api, "IN", [(p, 10)])
    act(api, o["id"], "todo")
    body = {"lines": [{"line_id": ok(api.get(f"/operations/{o['id']}"))["lines"][0]["id"], "done_qty": 4}], "backorder": True}
    done = ok(api.post(f"/operations/{o['id']}/validate", json=body))
    assert any("Backorder" in (h["detail"] or "") for h in ok(api.get(f"/operations/{o['id']}/history")))
    copy = ok(api.post(f"/operations/{done['id']}/duplicate"))
    assert any(h["action"] == "duplicate" for h in ok(api.get(f"/operations/{done['id']}/history")))
    assert ok(api.get(f"/operations/{copy['id']}/history"))[0]["detail"] == f"copy of {done['reference']}"


def test_stock_counts_settings_and_users_are_recorded(api, make_user):
    p = product(api, stock=10)
    ok(api.post("/stock/adjust", json={"product_id": p["id"], "location_id": main_loc(api)["id"], "counted_qty": 7}))
    row = audit(api, entity="stock", entity_id=p["id"])[0]
    assert row["action"] == "adjust" and row["changes"] == {"on_hand": [10, 7]} and row["detail"].startswith("WH/ADJ/")

    tax = ok(api.post("/taxes", json={"name": f"Aud {uid()}", "rate": 4, "kind": "OTHER"}), 201)
    ok(api.put(f"/taxes/{tax['id']}", json={"name": tax["name"], "rate": 6, "kind": "OTHER", "active": True, "is_default": False}))
    assert audit(api, entity="tax", entity_id=tax["id"])[0]["changes"] == {"rate": [4, 6]}

    u = make_user("staff")
    uid_ = ok(u.get("/auth/me"))["id"]
    ok(api.put(f"/users/{uid_}", json={"role": "manager", "active": True}))
    row = audit(api, entity="user", entity_id=uid_, action="role")[0]
    assert row["changes"] == {"role": ["staff", "manager"]}


def test_audit_filters_search_and_paging(api):
    p = product(api, name=f"Auditable {uid()}")
    rows = audit(api, q=p["sku"])
    assert rows and all(p["sku"] in (r["label"] or "") for r in rows)
    assert all(r["user"] == "pytest_admin" for r in audit(api, user="pytest_admin", entity="product"))
    assert all(r["action"] == "create" for r in audit(api, action="create", entity="product"))
    page = ok(api.get("/audit?page=1&page_size=2"))
    assert page["page_size"] == 2 and len(page["items"]) == 2 and page["total"] > 2
    ts = [r["at"] for r in audit(api)]
    assert ts == sorted(ts, reverse=True)


def test_signups_and_password_changes_are_recorded(api, anon):
    from conftest import PASSWORD
    login = f"aud{uid(5).lower()}"
    r = ok(anon.post("/auth/signup", json={"login_id": login, "email": f"{login}@example.com", "password": PASSWORD, "confirm_password": PASSWORD}), 201)
    from conftest import Api
    me = Api(anon.client, r["token"])
    ok(me.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "New!Passw0rd", "confirm_password": "New!Passw0rd"}))
    actions = [x["action"] for x in audit(api, entity="user", entity_id=r["user"]["id"])]
    assert actions == ["password", "signup"]
