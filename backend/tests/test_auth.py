from conftest import PASSWORD
from helpers import detail, ok, uid


def signup(anon, login_id=None, email=None, password=PASSWORD, confirm=None):
    login_id = login_id or f"user{uid(5)}"
    return anon.post("/auth/signup", json={
        "login_id": login_id, "email": email or f"{login_id}@example.com", "password": password,
        "confirm_password": confirm if confirm is not None else password,
    })


def test_signup_and_login(anon):
    body = ok(signup(anon, "login_ok1"), 201)
    assert body["token"] and body["user"]["login_id"] == "login_ok1"
    assert ok(anon.post("/auth/login", json={"login_id": "login_ok1", "password": PASSWORD}))["token"]
    assert ok(anon.post("/auth/login", json={"login_id": "LOGIN_OK1", "password": PASSWORD}))["token"]  # case-insensitive id


def test_wrong_password_message(anon):
    signup(anon, "login_bad")
    r = anon.post("/auth/login", json={"login_id": "login_bad", "password": "nope"})
    assert detail(r, 401) == "Invalid Login Id or Password"
    assert detail(anon.post("/auth/login", json={"login_id": "ghost_user", "password": "x"}), 401) == "Invalid Login Id or Password"


def test_signup_rules(anon):
    assert "6 and 12" in detail(signup(anon, "abc"), 422)
    assert "6 and 12" in detail(signup(anon, "waytoolongloginid"), 422)
    assert "special" in detail(signup(anon, password="NoSpecial123"), 422)
    assert "uppercase" in detail(signup(anon, password="lower!case123"), 422)
    assert "lowercase" in detail(signup(anon, password="UPPER!CASE123"), 422)
    assert "more than 8" in detail(signup(anon, password="Ab!12345"), 422)
    assert "match" in detail(signup(anon, confirm="Different!123"), 422)


def test_signup_uniqueness(anon):
    ok(signup(anon, "dup_login", "dup@example.com"), 201)
    assert "Login ID" in detail(signup(anon, "dup_login", "other@example.com"), 409)
    assert "Email" in detail(signup(anon, "dup_other", "dup@example.com"), 409)


def test_protected_routes_need_a_token(anon):
    assert anon.get("/products").status_code == 401
    assert anon.get("/dashboard").status_code == 401


def test_otp_reset_flow(anon, sent_otps):
    signup(anon, "otp_user1", "otp1@example.com")
    ok(anon.post("/auth/forgot-password", json={"email": "otp1@example.com"}))
    assert len(sent_otps) == 1
    email, code = sent_otps[0]
    assert email == "otp1@example.com" and len(code) == 6

    wrong = anon.post("/auth/reset-password", json={"email": email, "otp": "000000" if code != "000000" else "111111",
                                                    "new_password": "New!Passw0rd", "confirm_password": "New!Passw0rd"})
    assert detail(wrong, 400) == "Incorrect code"

    body = {"email": email, "otp": code, "new_password": "New!Passw0rd", "confirm_password": "New!Passw0rd"}
    ok(anon.post("/auth/reset-password", json=body))
    assert ok(anon.post("/auth/login", json={"login_id": "otp_user1", "password": "New!Passw0rd"}))["token"]
    assert anon.post("/auth/login", json={"login_id": "otp_user1", "password": PASSWORD}).status_code == 401
    # a code works once
    assert detail(anon.post("/auth/reset-password", json=body), 400)


def test_otp_unknown_email_looks_the_same(anon, sent_otps):
    r = ok(anon.post("/auth/forgot-password", json={"email": "nobody@example.com"}))
    assert "registered" in r["message"]
    assert sent_otps == []  # nothing was sent, and the answer didn't reveal that


def test_otp_locks_after_five_wrong_tries(anon, sent_otps):
    signup(anon, "otp_user2", "otp2@example.com")
    anon.post("/auth/forgot-password", json={"email": "otp2@example.com"})
    _, code = sent_otps[0]
    wrong = "000000" if code != "000000" else "111111"
    body = {"email": "otp2@example.com", "otp": wrong, "new_password": "New!Passw0rd", "confirm_password": "New!Passw0rd"}
    for _ in range(5):
        assert anon.post("/auth/reset-password", json=body).status_code == 400
    body["otp"] = code  # even the right code is refused now
    assert "expired or invalid" in detail(anon.post("/auth/reset-password", json=body), 400)


def test_change_password_and_profile(anon):
    token = ok(signup(anon, "prof_user1", "prof1@example.com"), 201)["token"]
    from conftest import Api
    me = Api(anon.client, token)

    assert detail(me.post("/auth/change-password", json={"current_password": "bad", "new_password": "New!Passw0rd", "confirm_password": "New!Passw0rd"}), 400)
    assert "different" in detail(me.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": PASSWORD, "confirm_password": PASSWORD}), 422)
    assert "special" in detail(me.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "Weakpass123", "confirm_password": "Weakpass123"}), 422)
    ok(me.post("/auth/change-password", json={"current_password": PASSWORD, "new_password": "New!Passw0rd", "confirm_password": "New!Passw0rd"}))
    assert ok(anon.post("/auth/login", json={"login_id": "prof_user1", "password": "New!Passw0rd"}))["token"]

    assert ok(me.put("/auth/me", json={"email": "Changed@Example.com"}))["email"] == "changed@example.com"
    signup(anon, "prof_user2", "taken@example.com")
    assert "Email" in detail(me.put("/auth/me", json={"email": "taken@example.com"}), 409)
