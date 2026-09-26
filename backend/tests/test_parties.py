import csv
import io

from app.routers.parties import gstin_check_char
from helpers import act, detail, make_op, ok, party, product, receive, uid

# real, publicly documented GSTINs (used only to prove the check-digit maths)
VALID_GSTINS = ["27AAPFU0939F1ZV", "24AAACC1206D1ZM", "07AAGFF2194N1Z1"]


def with_check_digit(first14: str) -> str:
    return first14 + gstin_check_char(first14)


def test_check_digit_matches_real_gstins():
    for g in VALID_GSTINS:
        assert gstin_check_char(g[:14]) == g[14], g


def test_create_contact_with_a_valid_gstin(api):
    g = VALID_GSTINS[0]
    p = party(api, "vendor", gstin=g.lower(), email="Sales@Example.com", phone="98765 43210", address="Plot 1, Pune")
    assert p["gstin"] == g and p["state"] == "Maharashtra"  # normalised, and the state comes from the code
    assert p["kind"] == "vendor" and p["active"] is True


def test_gstin_is_validated(api):
    body = lambda g: {"name": f"P {uid()}", "gstin": g}
    assert "15 characters" in detail(api.post("/parties", json=body("SHORT")), 422)
    assert "15 characters" in detail(api.post("/parties", json=body("27aapfu0939f1z")), 422)
    assert "unknown state" in detail(api.post("/parties", json=body(with_check_digit("99AAPFU0939F1Z"))), 422)
    wrong = VALID_GSTINS[0][:14] + ("A" if VALID_GSTINS[0][14] != "A" else "B")
    assert "check digit" in detail(api.post("/parties", json=body(wrong)), 422)
    assert "check digit" in detail(api.post("/parties", json=body("22AAAAA0000A1Z5")), 422)  # the well-known dummy sample
    assert ok(api.post("/parties", json={"name": f"P {uid()}", "gstin": "  "}), 201)["gstin"] is None  # blank is fine


def test_contact_validation_and_uniqueness(api):
    p = party(api)
    assert "already exists" in detail(api.post("/parties", json={"name": p["name"].upper()}), 409)
    assert "Name is required" in detail(api.post("/parties", json={"name": "  "}), 422)
    assert "vendor, customer or both" in detail(api.post("/parties", json={"name": f"K {uid()}", "kind": "friend"}), 422)
    assert api.post("/parties", json={"name": f"E {uid()}", "email": "not-an-email"}).status_code == 422


def test_update_and_list_filters(api):
    v, c = party(api, "vendor"), party(api, "customer")
    both = party(api, "both")
    ok(api.put(f"/parties/{v['id']}", json={"name": v["name"] + " Ltd", "kind": "vendor", "address": "New address"}))
    ids = lambda q: [x["id"] for x in ok(api.get(f"/parties?{q}"))]
    assert v["id"] in ids("kind=vendor") and both["id"] in ids("kind=vendor") and c["id"] not in ids("kind=vendor")
    assert c["id"] in ids("kind=customer") and v["id"] not in ids("kind=customer")
    assert v["id"] in ids(f"q={v['name'].split()[1]}")


def test_documents_use_the_chosen_contact(api):
    vendor = party(api, "vendor", address="Vendor Street", gstin=VALID_GSTINS[2])
    p = product(api)
    o = make_op(api, "IN", [(p, 3)], party_id=vendor["id"], contact="ignored free text")
    assert o["contact"] == vendor["name"] and o["party"]["id"] == vendor["id"]
    assert o["party"]["gstin"] == VALID_GSTINS[2] and o["party"]["address"] == "Vendor Street"
    assert o["party"]["state"] == "Delhi"

    other = party(api, "vendor")
    moved = ok(api.put(f"/operations/{o['id']}", json={"type": "IN", "party_id": other["id"], "lines": [{"product_id": p["id"], "quantity": 3}]}))
    assert moved["party"]["id"] == other["id"] and moved["contact"] == other["name"]

    freetext = ok(api.put(f"/operations/{o['id']}", json={"type": "IN", "contact": "Walk-in seller", "lines": [{"product_id": p["id"], "quantity": 3}]}))
    assert freetext["party"] is None and freetext["contact"] == "Walk-in seller"  # the link can be cleared


def test_a_contact_must_suit_the_document(api):
    customer, vendor = party(api, "customer"), party(api, "vendor")
    p = product(api)
    assert "not a supplier" in detail(api.post("/operations", json={"type": "IN", "party_id": customer["id"], "lines": [{"product_id": p["id"], "quantity": 1}]}), 422)
    assert "not a customer" in detail(api.post("/operations", json={"type": "OUT", "party_id": vendor["id"], "lines": [{"product_id": p["id"], "quantity": 1}]}), 422)
    assert "Unknown contact" in detail(api.post("/operations", json={"type": "IN", "party_id": 999999, "lines": []}), 422)
    both = party(api, "both")
    make_op(api, "IN", [(p, 1)], party_id=both["id"])
    make_op(api, "OUT", [(p, 1)], party_id=both["id"])


def test_contact_history_and_totals(api):
    customer = party(api, "customer")
    p = product(api, stock=20, unit_cost=100)
    o = make_op(api, "OUT", [(p, 2)], party_id=customer["id"])  # 200 + 18% = 236
    act(api, o["id"], "todo")
    make_op(api, "OUT", [(p, 1)], party_id=customer["id"])  # 118
    cancelled = make_op(api, "OUT", [(p, 5)], party_id=customer["id"])
    act(api, cancelled["id"], "cancel")  # doesn't count
    detail_ = ok(api.get(f"/parties/{customer['id']}"))
    assert detail_["documents"] == 2 and detail_["total_value"] == 354
    assert len(detail_["recent"]) == 3 and detail_["recent"][0]["reference"].startswith("WH/OUT/")
    row = next(x for x in ok(api.get("/parties")) if x["id"] == customer["id"])
    assert row["documents"] == 2 and row["last_document"]


def test_archive_and_delete_rules(api):
    used, unused = party(api, "vendor"), party(api, "vendor")
    p = product(api)
    o = make_op(api, "IN", [(p, 2)], party_id=used["id"])
    assert "open document" in detail(api.post(f"/parties/{used['id']}/archive"), 409)
    act(api, o["id"], "todo")
    act(api, o["id"], "validate")
    assert ok(api.post(f"/parties/{used['id']}/archive"))["active"] is False
    assert used["id"] not in [x["id"] for x in ok(api.get("/parties"))]
    assert used["id"] in [x["id"] for x in ok(api.get("/parties?include_archived=true"))]
    assert "archived" in detail(api.post("/operations", json={"type": "IN", "party_id": used["id"], "lines": [{"product_id": p["id"], "quantity": 1}]}), 422)
    assert "archive it instead" in detail(api.delete(f"/parties/{used['id']}"), 409)
    assert ok(api.post(f"/parties/{used['id']}/restore"))["active"] is True
    assert ok(api.delete(f"/parties/{unused['id']}"))["ok"] is True


def test_export_contacts(api):
    p = party(api, "customer", gstin=VALID_GSTINS[0], email="x@example.com")
    r = api.get("/export/parties.csv")
    assert r.status_code == 200 and r.text.startswith("﻿")
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    mine = next(x for x in rows if x["name"] == p["name"])
    assert mine["gstin"] == VALID_GSTINS[0] and mine["state"] == "Maharashtra" and mine["type"] == "customer"
